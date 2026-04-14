/*******************************************************************************
 * IDS Engine — Sliding window rate limiter + size anomaly detection
 ******************************************************************************/

#include "ids_engine.h"
#include "definitions.h"
#include <string.h>

void ids_init(ids_engine_t *ids) {
    memset(ids, 0, sizeof(*ids));
}

void ids_register_channel(ids_engine_t *ids, uint16_t data_id) {
    if (ids->channel_count >= IDS_MAX_CHANNELS) return;
    ids_channel_t *ch = &ids->channels[ids->channel_count++];
    memset(ch, 0, sizeof(*ch));
    ch->data_id = data_id;
}

static ids_channel_t *find_channel(ids_engine_t *ids, uint16_t data_id) {
    for (uint8_t i = 0; i < ids->channel_count; i++) {
        if (ids->channels[i].data_id == data_id)
            return &ids->channels[i];
    }
    return NULL;
}

/* Purge timestamps older than window */
static uint8_t count_in_window(ids_channel_t *ch, uint32_t now) {
    uint8_t count = 0;
    uint32_t window_start = now - pdMS_TO_TICKS(IDS_RATE_WINDOW_MS);
    for (uint8_t i = 0; i < ch->ts_count; i++) {
        uint8_t idx = (ch->ts_head + i) % (IDS_RATE_MAX_MSG + 4);
        if ((int32_t)(ch->timestamps[idx] - window_start) >= 0)
            count++;
    }
    return count;
}

bool ids_check_message(ids_engine_t *ids, uint16_t data_id,
                       uint32_t msg_size, uint32_t current_tick) {
    ids_channel_t *ch = find_channel(ids, data_id);
    if (!ch) return true;  /* unregistered channel: allow */

    ch->total_msgs++;

    /* Rate check: sliding window */
    uint8_t recent = count_in_window(ch, current_tick);
    if (recent >= IDS_RATE_MAX_MSG) {
        ch->total_dropped++;
        ids->total_alerts++;
        SYS_CONSOLE_PRINT("[IDS] Rate limit: data_id=0x%04X (%u/s)\r\n",
                          data_id, recent);
        return false;
    }

    /* Record timestamp */
    uint8_t slot = (ch->ts_head + ch->ts_count) % (IDS_RATE_MAX_MSG + 4);
    ch->timestamps[slot] = current_tick;
    if (ch->ts_count < IDS_RATE_MAX_MSG + 4)
        ch->ts_count++;
    else
        ch->ts_head = (ch->ts_head + 1) % (IDS_RATE_MAX_MSG + 4);

    /* Size anomaly check */
    if (ch->total_msgs <= 10) {
        /* Build baseline */
        ch->avg_size = (ch->avg_size * (ch->total_msgs - 1) + msg_size) / ch->total_msgs;
    } else {
        if (ch->avg_size > 0 && msg_size > ch->avg_size * IDS_SIZE_ANOMALY_FACTOR) {
            ch->anomaly_count++;
            ids->total_alerts++;
            SYS_CONSOLE_PRINT("[IDS] Size anomaly: data_id=0x%04X size=%lu avg=%lu\r\n",
                              data_id, (unsigned long)msg_size, (unsigned long)ch->avg_size);
        }
        /* Update running average (exponential moving avg) */
        ch->avg_size = (ch->avg_size * 7 + msg_size) / 8;
    }

    return true;
}

uint32_t ids_get_total_alerts(const ids_engine_t *ids) {
    return ids->total_alerts;
}

uint32_t ids_get_dropped(const ids_engine_t *ids, uint16_t data_id) {
    for (uint8_t i = 0; i < ids->channel_count; i++) {
        if (ids->channels[i].data_id == data_id)
            return ids->channels[i].total_dropped;
    }
    return 0;
}
