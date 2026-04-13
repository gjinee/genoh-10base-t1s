/**
 * Zenoh-pico sensor node example for 10BASE-T1S.
 *
 * Simulates a temperature sensor slave node that:
 * 1. Connects to the zenohd router as a client
 * 2. Declares a liveliness token (vehicle/{zone}/{node_id}/alive)
 * 3. Periodically publishes sensor data (vehicle/{zone}/{node_id}/sensor/temperature)
 * 4. Responds to status queries (vehicle/{zone}/{node_id}/status)
 *
 * Build: cmake --build build
 * Usage: ./sensor_node -e tcp/192.168.1.1:7447 -z front_left -n 1
 *
 * PRD References: FR-003 (sensor subscribe), FR-006 (liveliness)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>

#include "zenoh-pico.h"

#define DEFAULT_ROUTER  "tcp/192.168.1.1:7447"
#define DEFAULT_ZONE    "front_left"
#define DEFAULT_NODE_ID "1"
#define PUBLISH_INTERVAL_MS 1000

/* Simulated sensor reading */
static float read_temperature(void) {
    /* Simulate temperature: 20-30°C with ±0.5 drift */
    return 25.0f + ((float)(rand() % 100) - 50.0f) / 10.0f;
}

/* Status query handler */
void query_handler(z_query_t query, void *ctx) {
    const char *node_id = (const char *)ctx;

    /* Build status JSON response */
    char reply[256];
    snprintf(reply, sizeof(reply),
        "{\"alive\":true,\"uptime_sec\":%ld,\"firmware_version\":\"1.0.0\","
        "\"error_count\":0,\"plca_node_id\":%s,\"tx_count\":0,\"rx_count\":0}",
        (long)time(NULL), node_id);

    z_query_reply_options_t options;
    z_query_reply_options_default(&options);

    /* Reply with the key expression from the query */
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

    /* Parse arguments */
    int opt;
    while ((opt = getopt(argc, argv, "e:z:n:")) != -1) {
        switch (opt) {
            case 'e': router = optarg; break;
            case 'z': zone = optarg; break;
            case 'n': node_id = optarg; break;
            default:
                fprintf(stderr, "Usage: %s [-e router] [-z zone] [-n node_id]\n", argv[0]);
                return 1;
        }
    }

    srand((unsigned)time(NULL));

    /* Build key expressions */
    char sensor_ke[128], alive_ke[128], status_ke[128];
    snprintf(sensor_ke, sizeof(sensor_ke),
             "vehicle/%s/%s/sensor/temperature", zone, node_id);
    snprintf(alive_ke, sizeof(alive_ke),
             "vehicle/%s/%s/alive", zone, node_id);
    snprintf(status_ke, sizeof(status_ke),
             "vehicle/%s/%s/status", zone, node_id);

    printf("Sensor Node: zone=%s, node_id=%s\n", zone, node_id);
    printf("Router: %s\n", router);
    printf("Sensor key: %s\n", sensor_ke);
    printf("Alive key:  %s\n", alive_ke);
    printf("Status key: %s\n", status_ke);

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

    /* Start read/lease tasks (required for zenoh-pico) */
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

    /* Declare publisher for sensor data */
    z_view_keyexpr_t sensor_keyexpr;
    z_view_keyexpr_from_str(&sensor_keyexpr, sensor_ke);
    z_owned_publisher_t pub;
    z_declare_publisher(z_loan(session), &pub, z_loan(sensor_keyexpr), NULL);
    printf("Publisher declared: %s\n", sensor_ke);

    /* Declare queryable for status (PRD FR-005) */
    z_view_keyexpr_t status_keyexpr;
    z_view_keyexpr_from_str(&status_keyexpr, status_ke);
    z_owned_closure_query_t callback;
    z_closure(&callback, query_handler, NULL, (void *)node_id);
    z_owned_queryable_t queryable;
    z_declare_queryable(z_loan(session), &queryable, z_loan(status_keyexpr),
                        z_move(callback), NULL);
    printf("Queryable declared: %s\n", status_ke);

    /* Main publishing loop */
    printf("Publishing sensor data every %d ms (Ctrl+C to stop)...\n",
           PUBLISH_INTERVAL_MS);

    while (1) {
        float temp = read_temperature();
        long ts = (long)(time(NULL)) * 1000;

        /* Build JSON payload (PRD Section 5.2) */
        char payload[128];
        snprintf(payload, sizeof(payload),
                 "{\"value\":%.1f,\"unit\":\"celsius\",\"ts\":%ld}",
                 temp, ts);

        z_owned_bytes_t data;
        z_bytes_copy_from_str(&data, payload);
        z_publisher_put(z_loan(pub), z_move(data), NULL);

        printf("[%ld] Published: %s → %s\n", ts, sensor_ke, payload);

        usleep(PUBLISH_INTERVAL_MS * 1000);
    }

    /* Cleanup */
    z_undeclare_queryable(z_move(queryable));
    z_undeclare_publisher(z_move(pub));
    z_liveliness_undeclare_token(z_move(token));
    z_drop(z_move(session));

    return 0;
}
