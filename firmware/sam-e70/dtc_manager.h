#ifndef DTC_MANAGER_H
#define DTC_MANAGER_H
/*******************************************************************************
 * DTC Manager — Diagnostic Trouble Codes with Freeze Frame
 *
 * RAM-based ring buffer for recent DTCs. Each DTC includes a freeze frame
 * snapshot of system state at fault time.
 ******************************************************************************/

#include <stdint.h>
#include <stdbool.h>

/* DTC codes (UDS-style, 0xE0xx = manufacturer-specific) */
#define DTC_CRC_FAILURE   0xE001
#define DTC_SEQ_ERROR     0xE002
#define DTC_MAC_FAILURE   0xE003
#define DTC_REPLAY        0xE004
#define DTC_FLOOD         0xE005
#define DTC_WDT_RESET     0xE006
#define DTC_FLOW_ERROR    0xE007
#define DTC_SELF_TEST     0xE008

/* Maximum stored DTCs */
#define DTC_MAX_ENTRIES   16

/* Freeze frame: snapshot at fault time */
typedef struct {
    uint32_t tick;
    uint16_t last_seq;
    uint8_t  safety_state;
    uint8_t  fault_count;
} dtc_freeze_frame_t;

/* Single DTC entry */
typedef struct {
    uint16_t           code;
    uint8_t            occurrence_count;  /* capped at 255 */
    dtc_freeze_frame_t freeze;
} dtc_entry_t;

typedef struct {
    dtc_entry_t entries[DTC_MAX_ENTRIES];
    uint8_t     count;       /* total stored (up to DTC_MAX_ENTRIES) */
    uint8_t     write_idx;   /* next write position (ring) */
    uint32_t    total_dtcs;  /* lifetime DTC count */
} dtc_manager_t;

void dtc_init(dtc_manager_t *dm);

/* Record a DTC with freeze frame. If same code already stored, increment count. */
void dtc_record(dtc_manager_t *dm, uint16_t code,
                const dtc_freeze_frame_t *freeze);

/* Get number of active DTCs */
uint8_t dtc_get_count(const dtc_manager_t *dm);

/* Get DTC entry by index (0..count-1). Returns NULL if out of range. */
const dtc_entry_t *dtc_get_entry(const dtc_manager_t *dm, uint8_t index);

/* Clear all DTCs */
void dtc_clear(dtc_manager_t *dm);

/* Get total lifetime DTC count */
uint32_t dtc_get_total(const dtc_manager_t *dm);

#endif /* DTC_MANAGER_H */
