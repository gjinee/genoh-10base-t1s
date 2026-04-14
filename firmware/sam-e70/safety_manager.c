/*******************************************************************************
 * Safety Manager — ASIL-D FSM with fault tracking, self-test, safe actions
 ******************************************************************************/

#include "safety_manager.h"
#include "e2e_protection.h"
#include "secoc.h"
#include "definitions.h"
#include <string.h>
#include <stdio.h>

void safety_init(safety_manager_t *sm) {
    memset(sm, 0, sizeof(*sm));
    sm->state = SAFETY_NORMAL;
    sm->self_test_passed = false;
}

bool safety_self_test(safety_manager_t *sm) {
    bool pass = true;

    /* Test 1: CRC-32 known-answer test */
    const uint8_t test_data[] = "123456789";
    uint32_t crc = e2e_crc32(test_data, 9);
    if (crc != 0xCBF43926) {  /* IEEE 802.3 check value */
        SYS_CONSOLE_PRINT("[SAFETY] FAIL: CRC self-test (got 0x%08lX)\r\n",
                          (unsigned long)crc);
        pass = false;
    }

    /* Test 2: E2E encode/decode round-trip */
    const uint8_t payload[] = "{\"test\":1}";
    e2e_counter_state_t cnt = {0, 0};
    uint8_t buf[64];
    size_t encoded_len = e2e_encode(payload, 10, 0xFFFF, &cnt, buf, sizeof(buf));
    if (encoded_len != E2E_HEADER_SIZE + 10) {
        SYS_CONSOLE_PRINT("[SAFETY] FAIL: E2E encode self-test\r\n");
        pass = false;
    } else {
        e2e_header_t hdr;
        const uint8_t *p_out;
        size_t p_len;
        if (e2e_decode(buf, encoded_len, &hdr, &p_out, &p_len) != E2E_OK) {
            SYS_CONSOLE_PRINT("[SAFETY] FAIL: E2E decode self-test\r\n");
            pass = false;
        }
    }

    /* Test 3: Sequence counter initialization */
    if (cnt.seq != 1 || cnt.alive != 1) {
        SYS_CONSOLE_PRINT("[SAFETY] FAIL: Seq counter self-test\r\n");
        pass = false;
    }

    sm->self_test_passed = pass;
    if (pass) {
        SYS_CONSOLE_PRINT("[SAFETY] Self-test PASSED (CRC, E2E, SEQ)\r\n");
    } else {
        sm->state = SAFETY_SAFE_STATE;
        SYS_CONSOLE_PRINT("[SAFETY] Self-test FAILED → SAFE_STATE\r\n");
    }
    return pass;
}

void safety_report_fault(safety_manager_t *sm, fault_type_t fault) {
    if (sm->state == SAFETY_FAIL_SILENT) return;

    if (fault < FAULT_TYPE_COUNT)
        sm->fault_counts[fault]++;
    sm->total_faults++;
    sm->consecutive_ok = 0;

    SYS_CONSOLE_PRINT("[SAFETY] Fault #%lu type=%d state=%d\r\n",
                      (unsigned long)sm->total_faults, fault, sm->state);

    switch (sm->state) {
    case SAFETY_NORMAL:
        /* ASIL-D: single fault → DEGRADED */
        sm->state = SAFETY_DEGRADED;
        sm->degraded_enter_tick = xTaskGetTickCount();
        SYS_CONSOLE_PRINT("[SAFETY] NORMAL → DEGRADED\r\n");
        break;
    case SAFETY_DEGRADED:
        /* ASIL-D: 3 additional faults in DEGRADED → immediate SAFE_STATE */
        if (sm->total_faults >= 4) {
            sm->state = SAFETY_SAFE_STATE;
            SYS_CONSOLE_PRINT("[SAFETY] DEGRADED → SAFE_STATE (accumulated faults=%lu)\r\n",
                              (unsigned long)sm->total_faults);
            safety_execute_safe_action();
        }
        break;
    case SAFETY_SAFE_STATE:
        sm->state = SAFETY_FAIL_SILENT;
        SYS_CONSOLE_PRINT("[SAFETY] SAFE_STATE → FAIL_SILENT\r\n");
        safety_execute_safe_action();
        break;
    default:
        break;
    }
}

void safety_report_ok(safety_manager_t *sm) {
    if (sm->state == SAFETY_DEGRADED) {
        sm->consecutive_ok++;
        if (sm->consecutive_ok >= ASILD_RECOVERY_COUNT) {
            sm->state = SAFETY_NORMAL;
            sm->consecutive_ok = 0;
            SYS_CONSOLE_PRINT("[SAFETY] DEGRADED → NORMAL (recovered)\r\n");
        }
    }
}

void safety_tick(safety_manager_t *sm, uint32_t current_tick) {
    if (sm->state == SAFETY_DEGRADED) {
        uint32_t elapsed = current_tick - sm->degraded_enter_tick;
        if (elapsed >= pdMS_TO_TICKS(ASILD_DEGRADED_TIMEOUT)) {
            sm->state = SAFETY_SAFE_STATE;
            SYS_CONSOLE_PRINT("[SAFETY] DEGRADED → SAFE_STATE (timeout 30s)\r\n");
            safety_execute_safe_action();
        }
    }
}

safety_state_t safety_get_state(const safety_manager_t *sm) {
    return sm->state;
}

void safety_execute_safe_action(void) {
    /* Turn off all actuators */
    LED1_Off();
    LED2_Off();
    SYS_CONSOLE_PRINT("[SAFETY] Safe action: all actuators OFF\r\n");
}

bool safety_actuator_allowed(const safety_manager_t *sm) {
    return sm->state == SAFETY_NORMAL || sm->state == SAFETY_DEGRADED;
}

bool safety_periodic_test(safety_manager_t *sm) {
    bool pass = true;

    /* CRC-32 known-answer test */
    const uint8_t test_data[] = "123456789";
    uint32_t crc = e2e_crc32(test_data, 9);
    if (crc != 0xCBF43926) {
        pass = false;
    }

    /* HMAC-SHA256 known-answer test (RFC 4231 Test Case 2) */
    const uint8_t hmac_key[] = "Jefe";
    const uint8_t hmac_data[] = "what do ya want for nothing?";
    uint8_t hmac_out[32];
    hmac_sha256(hmac_key, 4, hmac_data, 28, hmac_out);
    /* Expected: 5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843 */
    const uint8_t hmac_expected[] = {
        0x5b,0xdc,0xc1,0x46,0xbf,0x60,0x75,0x4e,
        0x6a,0x04,0x24,0x26,0x08,0x95,0x75,0xc7,
        0x5a,0x00,0x3f,0x08,0x9d,0x27,0x39,0x83,
        0x9d,0xec,0x58,0xb9,0x64,0xec,0x38,0x43,
    };
    if (memcmp(hmac_out, hmac_expected, 32) != 0) {
        pass = false;
    }

    /* RAM pattern test (small area) */
    volatile uint32_t ram_test = 0xAA55AA55;
    if (ram_test != 0xAA55AA55) pass = false;
    ram_test = 0x55AA55AA;
    if (ram_test != 0x55AA55AA) pass = false;

    if (!pass) {
        SYS_CONSOLE_PRINT("[SAFETY] Periodic test FAILED\r\n");
        safety_report_fault(sm, FAULT_SELF_TEST);
    }
    return pass;
}
