/*******************************************************************************
 * DTC Manager — Ring buffer DTC storage with freeze frame
 ******************************************************************************/

#include "dtc_manager.h"
#include "definitions.h"
#include <string.h>

void dtc_init(dtc_manager_t *dm) {
    memset(dm, 0, sizeof(*dm));
}

void dtc_record(dtc_manager_t *dm, uint16_t code,
                const dtc_freeze_frame_t *freeze) {
    /* Check if DTC already stored — if so, increment count */
    for (uint8_t i = 0; i < dm->count; i++) {
        if (dm->entries[i].code == code) {
            if (dm->entries[i].occurrence_count < 255)
                dm->entries[i].occurrence_count++;
            dm->entries[i].freeze = *freeze;  /* update freeze frame */
            dm->total_dtcs++;
            return;
        }
    }

    /* New DTC: write to ring buffer */
    dtc_entry_t *e = &dm->entries[dm->write_idx];
    e->code = code;
    e->occurrence_count = 1;
    e->freeze = *freeze;

    dm->write_idx = (dm->write_idx + 1) % DTC_MAX_ENTRIES;
    if (dm->count < DTC_MAX_ENTRIES)
        dm->count++;
    dm->total_dtcs++;

    SYS_CONSOLE_PRINT("[DTC] Recorded 0x%04X (total=%lu)\r\n",
                      code, (unsigned long)dm->total_dtcs);
}

uint8_t dtc_get_count(const dtc_manager_t *dm) {
    return dm->count;
}

const dtc_entry_t *dtc_get_entry(const dtc_manager_t *dm, uint8_t index) {
    if (index >= dm->count) return NULL;
    return &dm->entries[index];
}

void dtc_clear(dtc_manager_t *dm) {
    dm->count = 0;
    dm->write_idx = 0;
    memset(dm->entries, 0, sizeof(dm->entries));
    SYS_CONSOLE_PRINT("[DTC] Cleared all DTCs\r\n");
}

uint32_t dtc_get_total(const dtc_manager_t *dm) {
    return dm->total_dtcs;
}
