#ifndef IDS_ENGINE_H
#define IDS_ENGINE_H
/*******************************************************************************
 * IDS Engine — Rate Limiter + Anomaly Detection (ISO/SAE 21434)
 *
 * Per-channel sliding window rate limiting with size anomaly detection.
 ******************************************************************************/

#include <stdint.h>
#include <stdbool.h>

/* Maximum monitored channels */
#define IDS_MAX_CHANNELS  4

/* Rate limit: max messages per window */
#define IDS_RATE_WINDOW_MS  1000   /* 1-second sliding window */
#define IDS_RATE_MAX_MSG    20     /* max 20 msg/s per channel */

/* Anomaly: message size deviation threshold */
#define IDS_SIZE_ANOMALY_FACTOR  3  /* 3x average = anomaly */

typedef struct {
    uint16_t data_id;
    uint32_t timestamps[IDS_RATE_MAX_MSG + 4]; /* circular buffer */
    uint8_t  ts_head;
    uint8_t  ts_count;
    uint32_t total_msgs;
    uint32_t total_dropped;
    uint32_t avg_size;       /* running average message size */
    uint32_t anomaly_count;
} ids_channel_t;

typedef struct {
    ids_channel_t channels[IDS_MAX_CHANNELS];
    uint8_t       channel_count;
    uint32_t      total_alerts;
} ids_engine_t;

void ids_init(ids_engine_t *ids);
void ids_register_channel(ids_engine_t *ids, uint16_t data_id);

/* Check incoming message. Returns true if allowed, false if rate-limited. */
bool ids_check_message(ids_engine_t *ids, uint16_t data_id,
                       uint32_t msg_size, uint32_t current_tick);

/* Get stats for reporting */
uint32_t ids_get_total_alerts(const ids_engine_t *ids);
uint32_t ids_get_dropped(const ids_engine_t *ids, uint16_t data_id);

#endif /* IDS_ENGINE_H */
