/**
 * Zenoh-pico actuator node example for 10BASE-T1S.
 *
 * Simulates a door lock actuator slave node that:
 * 1. Connects to the zenohd router as a client
 * 2. Declares a liveliness token (vehicle/{zone}/{node_id}/alive)
 * 3. Subscribes to actuator commands (vehicle/{zone}/{node_id}/actuator/lock)
 * 4. Responds to status queries (vehicle/{zone}/{node_id}/status)
 *
 * Build: cmake --build build
 * Usage: ./actuator_node -e tcp/192.168.1.1:7447 -z front_left -n 2 -t lock
 *
 * PRD References: FR-004 (actuator publish), FR-006 (liveliness)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>

#include <zenoh-pico.h>

#define DEFAULT_ROUTER    "tcp/192.168.1.1:7447"
#define DEFAULT_ZONE      "front_left"
#define DEFAULT_NODE_ID   "2"
#define DEFAULT_ACT_TYPE  "lock"

static int rx_count = 0;
static int msg_target = 0;

/* Actuator command subscriber callback */
void on_actuator_command(z_loaned_sample_t *sample, void *ctx) {
    (void)ctx;
    rx_count++;

    z_view_string_t keystr;
    z_keyexpr_as_view_string(z_sample_keyexpr(sample), &keystr);

    z_owned_string_t payload_str;
    z_bytes_to_string(z_sample_payload(sample), &payload_str);

    printf(">> [Actuator] Received command on '%.*s': %.*s\n",
           (int)z_string_len(z_loan(keystr)),
           z_string_data(z_loan(keystr)),
           (int)z_string_len(z_loan(payload_str)),
           z_string_data(z_loan(payload_str)));

    const char *payload = z_string_data(z_loan(payload_str));
    if (strstr(payload, "\"unlock\"")) {
        printf("   -> Executing: UNLOCK\n");
    } else if (strstr(payload, "\"lock\"")) {
        printf("   -> Executing: LOCK\n");
    } else if (strstr(payload, "\"set\"")) {
        printf("   -> Executing: SET command\n");
    } else {
        printf("   -> Unknown action\n");
    }

    z_drop(z_move(payload_str));
}

static const char *g_node_id = DEFAULT_NODE_ID;

/* Status query handler */
void query_handler(z_loaned_query_t *query, void *ctx) {
    (void)ctx;

    char reply[256];
    snprintf(reply, sizeof(reply),
        "{\"alive\":true,\"uptime_sec\":%ld,\"firmware_version\":\"1.0.0\","
        "\"error_count\":0,\"plca_node_id\":%s,\"rx_count\":%d,\"tx_count\":0}",
        (long)time(NULL), g_node_id, rx_count);

    z_owned_bytes_t payload;
    z_bytes_copy_from_str(&payload, reply);

    z_query_reply(query, z_query_keyexpr(query), z_move(payload), NULL);
}

int main(int argc, char **argv) {
    const char *router = DEFAULT_ROUTER;
    const char *zone = DEFAULT_ZONE;
    const char *node_id = DEFAULT_NODE_ID;
    const char *act_type = DEFAULT_ACT_TYPE;

    int opt;
    while ((opt = getopt(argc, argv, "e:z:n:t:c:")) != -1) {
        switch (opt) {
            case 'e': router = optarg; break;
            case 'z': zone = optarg; break;
            case 'n': node_id = optarg; break;
            case 't': act_type = optarg; break;
            case 'c': msg_target = atoi(optarg); break;
            default:
                fprintf(stderr,
                    "Usage: %s [-e router] [-z zone] [-n node_id] [-t type] [-c count]\n",
                    argv[0]);
                return 1;
        }
    }

    g_node_id = node_id;

    char actuator_ke[128], alive_ke[128], status_ke[128];
    snprintf(actuator_ke, sizeof(actuator_ke),
             "vehicle/%s/%s/actuator/%s", zone, node_id, act_type);
    snprintf(alive_ke, sizeof(alive_ke),
             "vehicle/%s/%s/alive", zone, node_id);
    snprintf(status_ke, sizeof(status_ke),
             "vehicle/%s/%s/status", zone, node_id);

    printf("Actuator Node: zone=%s, node_id=%s, type=%s\n", zone, node_id, act_type);
    printf("Router: %s\n", router);
    printf("Actuator key: %s\n", actuator_ke);
    printf("Alive key:    %s\n", alive_ke);
    printf("Status key:   %s\n", status_ke);

    /* Configure zenoh-pico session (client mode) */
    z_owned_config_t config;
    z_config_default(&config);
    zp_config_insert(z_loan_mut(config), Z_CONFIG_MODE_KEY, "client");
    zp_config_insert(z_loan_mut(config), Z_CONFIG_CONNECT_KEY, router);

    printf("Opening zenoh-pico session...\n");
    z_owned_session_t session;
    if (z_open(&session, z_move(config), NULL) < 0) {
        fprintf(stderr, "Failed to open zenoh session\n");
        return 1;
    }
    printf("Session opened successfully\n");

#if Z_FEATURE_LIVELINESS == 1
    /* Declare liveliness token (PRD FR-006) */
    z_view_keyexpr_t alive_keyexpr;
    z_view_keyexpr_from_str(&alive_keyexpr, alive_ke);
    z_owned_liveliness_token_t token;
    if (z_liveliness_declare_token(z_loan(session), &token, z_loan(alive_keyexpr), NULL) < 0) {
        fprintf(stderr, "Failed to declare liveliness token\n");
    } else {
        printf("Liveliness token declared: %s\n", alive_ke);
    }
#endif

#if Z_FEATURE_SUBSCRIPTION == 1
    /* Subscribe to actuator commands (PRD FR-004) */
    z_view_keyexpr_t act_keyexpr;
    z_view_keyexpr_from_str(&act_keyexpr, actuator_ke);
    z_owned_closure_sample_t callback;
    z_closure(&callback, on_actuator_command, NULL, NULL);
    z_owned_subscriber_t sub;
    if (z_declare_subscriber(z_loan(session), &sub, z_loan(act_keyexpr),
                             z_move(callback), NULL) < 0) {
        fprintf(stderr, "Failed to declare subscriber\n");
        z_drop(z_move(session));
        return 1;
    }
    printf("Subscribed to actuator commands: %s\n", actuator_ke);
#endif

#if Z_FEATURE_QUERYABLE == 1
    /* Declare queryable for status (PRD FR-005) */
    z_view_keyexpr_t status_keyexpr;
    z_view_keyexpr_from_str(&status_keyexpr, status_ke);
    z_owned_closure_query_t qcallback;
    z_closure(&qcallback, query_handler, NULL, NULL);
    z_owned_queryable_t queryable;
    if (z_declare_queryable(z_loan(session), &queryable, z_loan(status_keyexpr),
                            z_move(qcallback), NULL) < 0) {
        fprintf(stderr, "Failed to declare queryable\n");
    } else {
        printf("Queryable declared: %s\n", status_ke);
    }
#endif

    printf("Waiting for actuator commands (Ctrl+C to stop)...\n");
    while (1) {
        if (msg_target > 0 && rx_count >= msg_target) {
            break;
        }
        z_sleep_s(1);
    }

    /* Cleanup */
#if Z_FEATURE_QUERYABLE == 1
    z_drop(z_move(queryable));
#endif
#if Z_FEATURE_SUBSCRIPTION == 1
    z_drop(z_move(sub));
#endif
#if Z_FEATURE_LIVELINESS == 1
    z_drop(z_move(token));
#endif
    z_drop(z_move(session));

    return 0;
}
