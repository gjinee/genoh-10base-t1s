/*******************************************************************************
 * Zenoh-pico Bidirectional Control on SAM E70 + 10BASE-T1S
 *
 * ASIL-D Functional Safety + ISO/SAE 21434 Cybersecurity
 *
 * Features: E2E Protection, SecOC (HMAC-SHA256), Safety FSM, HW Watchdog,
 *           IDS Rate Limiter, DTC Manager, Flow Monitor, Key Management,
 *           Periodic Self-Test, Replay Protection
 *
 * Wire: [E2E Header 11B][JSON payload][Freshness 8B][MAC 16B]
 ******************************************************************************/

#include <stdio.h>
#include <string.h>
#include "definitions.h"
#include "FreeRTOS.h"
#include "task.h"

#include "zenoh-pico/api/primitives.h"
#include "zenoh-pico/api/types.h"
#include "zenoh-pico/api/macros.h"

#include "drv_mcp3204.h"
#include "e2e_protection.h"
#include "secoc.h"
#include "safety_manager.h"
#include "watchdog.h"
#include "ids_engine.h"
#include "dtc_manager.h"
#include "flow_monitor.h"
#include "key_manager.h"

/* ---- Configuration ---- */
#define ZENOH_ROUTER            "tcp/192.168.100.1:7447"
#define ZONE                    "front_left"
#define NODE_ID                 "1"
#define STEERING_INTERVAL_MS    100
#define HAZARD_BLINK_MS         500
#define SELF_TEST_INTERVAL_MS   10000  /* periodic self-test every 10s */

/* ---- Key Expressions ---- */
#define KE_HEADLIGHT  "vehicle/" ZONE "/" NODE_ID "/actuator/headlight"
#define KE_HAZARD     "vehicle/" ZONE "/" NODE_ID "/actuator/hazard"
#define KE_STEERING   "vehicle/" ZONE "/" NODE_ID "/sensor/steering"

/* ---- Global State ---- */
static volatile bool headlight_on = false;
static volatile bool hazard_on    = false;
static volatile TickType_t hazard_last_toggle = 0;
static uint32_t sw0_press_count = 0;
static bool     use_thumbstick  = false;

/* Safety & Security subsystems */
static safety_manager_t    g_safety;
static e2e_counter_state_t g_steering_counter = {0, 0};
static e2e_seq_checker_t   g_headlight_checker;
static e2e_seq_checker_t   g_hazard_checker;
static secoc_freshness_t   g_steering_freshness = {0};
static ids_engine_t        g_ids;
static dtc_manager_t       g_dtc;
static flow_monitor_t      g_flow;
static key_manager_t       g_key;
static uint32_t            g_last_self_test_tick = 0;

/* ---- JSON parser ---- */
static bool json_get_string(const char *json, const char *key,
                            char *out, int out_size) {
    char search[32];
    int slen = snprintf(search, sizeof(search), "\"%s\"", key);
    if (slen <= 0) return false;
    const char *p = strstr(json, search);
    if (!p) return false;
    p += slen;
    while (*p == ':' || *p == ' ' || *p == '\t') p++;
    if (*p != '"') return false;
    p++;
    int i = 0;
    while (*p && *p != '"' && i < out_size - 1) out[i++] = *p++;
    out[i] = '\0';
    return i > 0;
}

/* ---- DTC helper ---- */
static void record_dtc(uint16_t code, uint16_t last_seq) {
    dtc_freeze_frame_t ff = {
        .tick = xTaskGetTickCount(),
        .last_seq = last_seq,
        .safety_state = (uint8_t)safety_get_state(&g_safety),
        .fault_count = (uint8_t)g_safety.total_faults,
    };
    dtc_record(&g_dtc, code, &ff);
}

/* ---- Decode incoming SecOC+E2E message ---- */
static bool decode_secure_message(const uint8_t *raw, size_t raw_len,
                                  e2e_header_t *hdr,
                                  char *json_out, size_t json_out_size,
                                  e2e_seq_checker_t *seq_chk,
                                  uint16_t data_id_expected) {
    /* IDS rate check */
    if (!ids_check_message(&g_ids, data_id_expected,
                           (uint32_t)raw_len, xTaskGetTickCount())) {
        safety_report_fault(&g_safety, FAULT_FLOOD);
        record_dtc(DTC_FLOOD, 0);
        return false;
    }

    /* Step 1: SecOC MAC + replay check */
    size_t e2e_len;
    secoc_decode_result_t secoc_result;
    if (!secoc_decode_ex(raw, raw_len, key_get_node_key(&g_key),
                         &e2e_len, &secoc_result)) {
        safety_report_fault(&g_safety, FAULT_MAC_FAILURE);
        record_dtc(DTC_MAC_FAILURE, 0);
        return false;
    }
    if (!secoc_result.freshness_valid) {
        safety_report_fault(&g_safety, FAULT_REPLAY);
        record_dtc(DTC_REPLAY, 0);
        SYS_CONSOLE_PRINT("[SEC] Replay REJECTED (freshness out of window)\r\n");
        return false;  /* ASIL-D: reject replayed messages */
    }

    /* Step 2: E2E decode + CRC verify */
    const uint8_t *payload;
    size_t payload_len;
    e2e_status_t st = e2e_decode(raw, e2e_len, hdr, &payload, &payload_len);
    if (st != E2E_OK) {
        safety_report_fault(&g_safety, FAULT_CRC_FAILURE);
        record_dtc(DTC_CRC_FAILURE, hdr->sequence_counter);
        return false;
    }

    /* Step 3: Sequence check (ASIL-D: gap=1) */
    e2e_status_t seq_st = e2e_seq_check(seq_chk, hdr->sequence_counter);
    if (seq_st == E2E_ERR_SEQ_GAP || seq_st == E2E_ERR_SEQ_REPEATED) {
        safety_report_fault(&g_safety, FAULT_SEQ_ERROR);
        record_dtc(DTC_SEQ_ERROR, hdr->sequence_counter);
        return false;
    }

    /* Step 4: Extract JSON */
    if (payload_len >= json_out_size) return false;
    memcpy(json_out, payload, payload_len);
    json_out[payload_len] = '\0';

    safety_report_ok(&g_safety);
    flow_actuator_received(&g_flow, xTaskGetTickCount());
    return true;
}

/* ---- Headlight subscriber ---- */
static void headlight_handler(z_loaned_sample_t *sample, void *ctx) {
    (void)ctx;
    z_owned_slice_t slice;
    z_bytes_to_slice(z_sample_payload(sample), &slice);
    const uint8_t *raw = z_slice_data(z_loan(slice));
    size_t raw_len = z_slice_len(z_loan(slice));

    char json[64];
    e2e_header_t hdr;
    bool secure = false;

    if (raw_len > E2E_HEADER_SIZE + SECOC_OVERHEAD) {
        secure = decode_secure_message(raw, raw_len, &hdr, json, sizeof(json),
                                       &g_headlight_checker, DATA_ID_HEADLIGHT);
    }
    if (!secure) {
        /* ASIL-D: No plain JSON fallback — reject unsecured messages */
        SYS_CONSOLE_PRINT("[SEC] Headlight: unsecured message REJECTED\r\n");
        z_drop(z_move(slice));
        return;
    }

    /* Verify data_id matches expected */
    if (hdr.data_id != DATA_ID_HEADLIGHT) {
        SYS_CONSOLE_PRINT("[SEC] Headlight: wrong data_id 0x%04X\r\n", hdr.data_id);
        safety_report_fault(&g_safety, FAULT_CRC_FAILURE);
        z_drop(z_move(slice));
        return;
    }

    if (!safety_actuator_allowed(&g_safety)) {
        z_drop(z_move(slice));
        return;
    }

    char state[8];
    if (json_get_string(json, "state", state, sizeof(state))) {
        if (strcmp(state, "on") == 0) {
            LED1_On(); headlight_on = true;
            SYS_CONSOLE_PRINT("[CTRL] Headlight ON [E2E+SecOC]\r\n");
        } else if (strcmp(state, "off") == 0) {
            LED1_Off(); headlight_on = false;
            SYS_CONSOLE_PRINT("[CTRL] Headlight OFF [E2E+SecOC]\r\n");
        }
    }
    z_drop(z_move(slice));
}

/* ---- Hazard subscriber ---- */
static void hazard_handler(z_loaned_sample_t *sample, void *ctx) {
    (void)ctx;
    z_owned_slice_t slice;
    z_bytes_to_slice(z_sample_payload(sample), &slice);
    const uint8_t *raw = z_slice_data(z_loan(slice));
    size_t raw_len = z_slice_len(z_loan(slice));

    char json[64];
    e2e_header_t hdr;
    bool secure = false;

    if (raw_len > E2E_HEADER_SIZE + SECOC_OVERHEAD) {
        secure = decode_secure_message(raw, raw_len, &hdr, json, sizeof(json),
                                       &g_hazard_checker, DATA_ID_HAZARD);
    }
    if (!secure) {
        SYS_CONSOLE_PRINT("[SEC] Hazard: unsecured message REJECTED\r\n");
        z_drop(z_move(slice));
        return;
    }

    if (hdr.data_id != DATA_ID_HAZARD) {
        SYS_CONSOLE_PRINT("[SEC] Hazard: wrong data_id 0x%04X\r\n", hdr.data_id);
        safety_report_fault(&g_safety, FAULT_CRC_FAILURE);
        z_drop(z_move(slice));
        return;
    }

    if (!safety_actuator_allowed(&g_safety)) {
        z_drop(z_move(slice));
        return;
    }

    char state[8];
    if (json_get_string(json, "state", state, sizeof(state))) {
        if (strcmp(state, "on") == 0) {
            hazard_on = true;
            hazard_last_toggle = xTaskGetTickCount();
            SYS_CONSOLE_PRINT("[CTRL] Hazard ON [E2E+SecOC]\r\n");
        } else if (strcmp(state, "off") == 0) {
            hazard_on = false;
            LED2_Off();
            SYS_CONSOLE_PRINT("[CTRL] Hazard OFF [E2E+SecOC]\r\n");
        }
    }
    z_drop(z_move(slice));
}

/* ---- Main Zenoh task ---- */
void zenoh_task(void *params) {
    (void)params;
    SYS_CONSOLE_PRINT("[ZENOH] === ASIL-D Secure Control Node ===\r\n");

    /* ---- Initialize all subsystems ---- */
    safety_init(&g_safety);
    e2e_seq_checker_init(&g_headlight_checker, E2E_ASILD_MAX_GAP);
    e2e_seq_checker_init(&g_hazard_checker, E2E_ASILD_MAX_GAP);
    ids_init(&g_ids);
    ids_register_channel(&g_ids, DATA_ID_HEADLIGHT);
    ids_register_channel(&g_ids, DATA_ID_HAZARD);
    dtc_init(&g_dtc);
    flow_init(&g_flow);
    key_init(&g_key, SECOC_TEST_KEY, ZONE "/" NODE_ID);

    /* Boot self-test */
    if (!safety_self_test(&g_safety)) {
        safety_execute_safe_action();
    }

    /* Watchdog */
    watchdog_init();
    watchdog_feed();
    SYS_CONSOLE_PRINT("[WDT] Initialized (~2s, ASIL-D)\r\n");

    /* Network wait */
    SYS_CONSOLE_PRINT("[ZENOH] Waiting for network...\r\n");
    vTaskDelay(pdMS_TO_TICKS(8000));
    watchdog_feed();

    /* MCP3204 init */
    MCP3204_Initialize();
    uint16_t test_ch[4];
    for (int ch = 0; ch < 4; ch++) test_ch[ch] = MCP3204_ReadChannel(ch);
    SYS_CONSOLE_PRINT("[MCP3204] CH0=%u CH1=%u CH2=%u CH3=%u\r\n",
                      test_ch[0], test_ch[1], test_ch[2], test_ch[3]);
    if ((test_ch[0] > 100 && test_ch[0] < 3995) ||
        (test_ch[1] > 100 && test_ch[1] < 3995)) {
        use_thumbstick = true;
        SYS_CONSOLE_PRINT("[CTRL] Thumbstick detected\r\n");
    } else {
        SYS_CONSOLE_PRINT("[CTRL] Phase 0: SW0 simulation\r\n");
    }
    watchdog_feed();

    /* ---- Zenoh connect ---- */
    SYS_CONSOLE_PRINT("[ZENOH] Connecting to %s\r\n", ZENOH_ROUTER);
    z_owned_session_t session;
    int connected = 0;
    for (int attempt = 0; attempt < 5; attempt++) {
        watchdog_feed();
        z_owned_config_t config;
        z_config_default(&config);
        zp_config_insert(z_loan_mut(config), Z_CONFIG_MODE_KEY, "client");
        zp_config_insert(z_loan_mut(config), Z_CONFIG_CONNECT_KEY, ZENOH_ROUTER);
        if (z_open(&session, z_move(config), NULL) == Z_OK) { connected = 1; break; }
        SYS_CONSOLE_PRINT("[ZENOH] Attempt %d failed\r\n", attempt + 1);
        vTaskDelay(pdMS_TO_TICKS(3000));
    }
    if (!connected) {
        SYS_CONSOLE_PRINT("[ZENOH] FATAL: Connect failed\r\n");
        vTaskDelete(NULL); return;
    }
    if (zp_start_read_task(z_loan_mut(session), NULL) != Z_OK ||
        zp_start_lease_task(z_loan_mut(session), NULL) != Z_OK) {
        z_drop(z_move(session)); vTaskDelete(NULL); return;
    }
    SYS_CONSOLE_PRINT("[ZENOH] Session opened\r\n");
    watchdog_feed();

    /* Publisher */
    z_owned_publisher_t pub_steering;
    z_view_keyexpr_t ke_steer;
    z_view_keyexpr_from_str(&ke_steer, KE_STEERING);
    z_declare_publisher(z_loan(session), &pub_steering,
                        z_view_keyexpr_loan(&ke_steer), NULL);
    SYS_CONSOLE_PRINT("[ZENOH] PUB: %s [E2E+SecOC+IDS+DTC]\r\n", KE_STEERING);

    /* Subscribers */
    z_owned_subscriber_t sub_hl, sub_hz;
    z_view_keyexpr_t ke_hl, ke_hz;
    z_view_keyexpr_from_str(&ke_hl, KE_HEADLIGHT);
    z_view_keyexpr_from_str(&ke_hz, KE_HAZARD);
    z_owned_closure_sample_t cb_hl, cb_hz;
    z_closure(&cb_hl, headlight_handler, NULL, NULL);
    z_closure(&cb_hz, hazard_handler, NULL, NULL);
    z_declare_subscriber(z_loan(session), &sub_hl,
                         z_view_keyexpr_loan(&ke_hl), z_move(cb_hl), NULL);
    z_declare_subscriber(z_loan(session), &sub_hz,
                         z_view_keyexpr_loan(&ke_hz), z_move(cb_hz), NULL);
    SYS_CONSOLE_PRINT("[ZENOH] SUB: headlight + hazard [ASIL-D secured]\r\n");

    /* ---- Main loop ---- */
    SYS_CONSOLE_PRINT("[ZENOH] Publishing every %d ms\r\n", STEERING_INTERVAL_MS);
    uint32_t msg_count = 0;
    g_last_self_test_tick = xTaskGetTickCount();

    while (1) {
        watchdog_feed();
        uint32_t now = xTaskGetTickCount();

        /* Safety tick + periodic self-test */
        safety_tick(&g_safety, now);
        if ((now - g_last_self_test_tick) >= pdMS_TO_TICKS(SELF_TEST_INTERVAL_MS)) {
            safety_periodic_test(&g_safety);
            g_last_self_test_tick = now;
        }

        /* Flow: checkpoint — sensor read */
        flow_checkpoint(&g_flow, CP_SENSOR_READ);

        thumbstick_data_t ts;
        if (use_thumbstick) {
            MCP3204_ReadThumbstick(&ts);
        } else {
            bool sw0 = (SWITCH_Get() == SWITCH_STATE_PRESSED);
            if (sw0) sw0_press_count++;
            uint16_t sim_x = 2048;
            if (sw0) sim_x = (sw0_press_count % 2 == 0) ? 1024 : 3072;
            ts.x = sim_x; ts.y = 2048;
            ts.btn = sw0 ? 1 : 0;
            ts.angle = MCP3204_CalcAngle(sim_x);
            ts.seq = msg_count;
        }

        /* Build JSON with extended fields */
        char json_payload[192];
        int json_len = snprintf(json_payload, sizeof(json_payload),
            "{\"x\":%u,\"y\":%u,\"btn\":%u,\"angle\":%.1f,\"seq\":%lu,"
            "\"safety\":%d,\"dtc_count\":%u,\"key_epoch\":%u}",
            ts.x, ts.y, ts.btn, (double)ts.angle,
            (unsigned long)ts.seq, (int)safety_get_state(&g_safety),
            dtc_get_count(&g_dtc), key_get_epoch(&g_key));

        /* Flow: checkpoint — E2E encode */
        flow_checkpoint(&g_flow, CP_E2E_ENCODE);

        uint8_t e2e_buf[300];
        size_t e2e_len = e2e_encode((const uint8_t *)json_payload, (size_t)json_len,
                                    DATA_ID_STEERING, &g_steering_counter,
                                    e2e_buf, sizeof(e2e_buf));

        /* Flow: checkpoint — SecOC encode */
        flow_checkpoint(&g_flow, CP_SECOC_ENCODE);

        uint8_t secoc_buf[400];
        size_t secoc_len = secoc_encode(e2e_buf, e2e_len,
                                        key_get_node_key(&g_key),
                                        &g_steering_freshness,
                                        secoc_buf, sizeof(secoc_buf));

        if (secoc_len > 0) {
            z_owned_bytes_t bytes;
            z_bytes_copy_from_buf(&bytes, secoc_buf, secoc_len);
            z_publisher_put(z_loan(pub_steering), z_move(bytes), NULL);
        }

        /* Flow: checkpoint — publish */
        flow_checkpoint(&g_flow, CP_PUBLISH);

        /* Verify flow cycle */
        if (!flow_verify_cycle(&g_flow)) {
            safety_report_fault(&g_safety, FAULT_FLOW);
            record_dtc(DTC_FLOW_ERROR, (uint16_t)msg_count);
        }

        /* Hazard blink */
        if (hazard_on && safety_actuator_allowed(&g_safety)) {
            if ((now - hazard_last_toggle) >= pdMS_TO_TICKS(HAZARD_BLINK_MS)) {
                LED2_Toggle();
                hazard_last_toggle = now;
            }
        }

        msg_count++;
        if ((msg_count % 50) == 0) {
            SYS_CONSOLE_PRINT("[STEER] #%lu safety=%d dtc=%u ids=%lu\r\n",
                              (unsigned long)msg_count,
                              (int)safety_get_state(&g_safety),
                              dtc_get_count(&g_dtc),
                              (unsigned long)ids_get_total_alerts(&g_ids));
        }

        vTaskDelay(pdMS_TO_TICKS(STEERING_INTERVAL_MS));
    }
}
