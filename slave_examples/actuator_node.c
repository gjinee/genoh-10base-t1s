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

#include "zenoh-pico.h"

#define DEFAULT_ROUTER    "tcp/192.168.1.1:7447"
#define DEFAULT_ZONE      "front_left"
#define DEFAULT_NODE_ID   "2"
#define DEFAULT_ACT_TYPE  "lock"

static int rx_count = 0;

/* Actuator command subscriber callback */
void on_actuator_command(z_sample_t sample, void *ctx) {
    (void)ctx;
    rx_count++;

    z_owned_string_t key_str;
    z_keyexpr_to_string(z_sample_keyexpr(&sample), &key_str);

    z_owned_string_t payload_str;
    z_bytes_to_string(z_sample_payload(&sample), &payload_str);

    printf(">> [Actuator] Received command on '%s': %s\n",
           z_string_data(z_loan(key_str)),
           z_string_data(z_loan(payload_str)));

    /* Parse action from JSON payload (simplified) */
    const char *payload = z_string_data(z_loan(payload_str));
    if (strstr(payload, "\"unlock\"") || strstr(payload, "\"action\":\"unlock\"")) {
        printf("   -> Executing: UNLOCK\n");
    } else if (strstr(payload, "\"lock\"") || strstr(payload, "\"action\":\"lock\"")) {
        printf("   -> Executing: LOCK\n");
    } else if (strstr(payload, "\"set\"")) {
        printf("   -> Executing: SET command\n");
    } else {
        printf("   -> Unknown action\n");
    }

    z_drop(z_move(key_str));
    z_drop(z_move(payload_str));
}

/* Status query handler */
void query_handler(z_query_t query, void *ctx) {
    const char *node_id = (const char *)ctx;

    char reply[256];
    snprintf(reply, sizeof(reply),
        "{\"alive\":true,\"uptime_sec\":%ld,\"firmware_version\":\"1.0.0\","
        "\"error_count\":0,\"plca_node_id\":%s,\"rx_count\":%d,\"tx_count\":0}",
        (long)time(NULL), node_id, rx_count);

    z_query_reply_options_t options;
    z_query_reply_options_default(&options);

    z_view_keyexpr_t ke;
    z_query_keyexpr(&query, &ke);

    z_owned_bytes_t payload;
    z_bytes_copy_from_str(&payload, reply);

    z_query_reply(&query, z_loan(ke), z_move(payload), &options);
}

int main(int argc, char **argv) {
    const char *router = DEFAULT_ROUTER;
    const char *zone = DEFAULT_ZONE;
    const char *node_id = DEFAULT_NODE_ID;
    const char *act_type = DEFAULT_ACT_TYPE;

    /* Parse arguments */
    int opt;
    while ((opt = getopt(argc, argv, "e:z:n:t:")) != -1) {
        switch (opt) {
            case 'e': router = optarg; break;
            case 'z': zone = optarg; break;
            case 'n': node_id = optarg; break;
            case 't': act_type = optarg; break;
            default:
                fprintf(stderr,
                    "Usage: %s [-e router] [-z zone] [-n node_id] [-t actuator_type]\n",
                    argv[0]);
                return 1;
        }
    }

    /* Build key expressions */
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

    /* Open session */
    printf("Opening zenoh-pico session...\n");
    z_owned_session_t session;
    if (z_open(&session, z_move(config), NULL) != Z_OK) {
        fprintf(stderr, "Failed to open zenoh session\n");
        return 1;
    }

    if (zp_start_read_task(z_loan_mut(session), NULL) != Z_OK ||
        zp_start_lease_task(z_loan_mut(session), NULL) != Z_OK) {
        fprintf(stderr, "Failed to start zenoh tasks\n");
        z_drop(z_move(session));
        return 1;
    }

    printf("Session opened successfully\n");

    /* Declare liveliness token (PRD FR-006) */
    z_view_keyexpr_t alive_keyexpr;
    z_view_keyexpr_from_str(&alive_keyexpr, alive_ke);
    z_owned_liveliness_token_t token;
    z_liveliness_declare_token(z_loan(session), &token, z_loan(alive_keyexpr), NULL);
    printf("Liveliness token declared: %s\n", alive_ke);

    /* Subscribe to actuator commands (PRD FR-004) */
    z_view_keyexpr_t act_keyexpr;
    z_view_keyexpr_from_str(&act_keyexpr, actuator_ke);
    z_owned_closure_sample_t callback;
    z_closure(&callback, on_actuator_command, NULL, NULL);
    z_owned_subscriber_t sub;
    z_declare_subscriber(z_loan(session), &sub, z_loan(act_keyexpr),
                         z_move(callback), NULL);
    printf("Subscribed to actuator commands: %s\n", actuator_ke);

    /* Declare queryable for status (PRD FR-005) */
    z_view_keyexpr_t status_keyexpr;
    z_view_keyexpr_from_str(&status_keyexpr, status_ke);
    z_owned_closure_query_t qcallback;
    z_closure(&qcallback, query_handler, NULL, (void *)node_id);
    z_owned_queryable_t queryable;
    z_declare_queryable(z_loan(session), &queryable, z_loan(status_keyexpr),
                        z_move(qcallback), NULL);
    printf("Queryable declared: %s\n", status_ke);

    /* Wait for commands */
    printf("Waiting for actuator commands (Ctrl+C to stop)...\n");
    while (1) {
        sleep(1);
    }

    /* Cleanup */
    z_undeclare_queryable(z_move(queryable));
    z_undeclare_subscriber(z_move(sub));
    z_liveliness_undeclare_token(z_move(token));
    z_drop(z_move(session));

    return 0;
}
