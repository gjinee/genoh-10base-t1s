/*******************************************************************************
 * Flow Monitor — Checkpoint verification + deadline monitoring
 ******************************************************************************/

#include "flow_monitor.h"
#include "definitions.h"
#include <string.h>

void flow_init(flow_monitor_t *fm) {
    memset(fm, 0, sizeof(*fm));
    fm->deadline_active = false;
}

void flow_checkpoint(flow_monitor_t *fm, flow_checkpoint_t cp) {
    if (cp < CP_COUNT)
        fm->checkpoints_hit |= (1U << cp);
}

bool flow_verify_cycle(flow_monitor_t *fm) {
    uint8_t expected = (1U << CP_COUNT) - 1;  /* all bits set */
    bool ok = (fm->checkpoints_hit == expected);
    if (!ok) {
        fm->total_flow_errors++;
        SYS_CONSOLE_PRINT("[FLOW] Checkpoint miss: got=0x%02X expected=0x%02X\r\n",
                          fm->checkpoints_hit, expected);
    }
    fm->checkpoints_hit = 0;  /* reset for next cycle */
    return ok;
}

void flow_actuator_received(flow_monitor_t *fm, uint32_t tick) {
    fm->last_actuator_tick = tick;
    fm->deadline_active = true;
}

bool flow_check_deadline(flow_monitor_t *fm, uint32_t current_tick) {
    if (!fm->deadline_active) return true;  /* no deadline until first msg */

    uint32_t elapsed = current_tick - fm->last_actuator_tick;
    if (elapsed > pdMS_TO_TICKS(FLOW_ACTUATOR_DEADLINE_MS)) {
        fm->total_deadline_misses++;
        return false;
    }
    return true;
}

uint32_t flow_get_errors(const flow_monitor_t *fm) {
    return fm->total_flow_errors;
}

uint32_t flow_get_deadline_misses(const flow_monitor_t *fm) {
    return fm->total_deadline_misses;
}
