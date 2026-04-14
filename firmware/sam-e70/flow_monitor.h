#ifndef FLOW_MONITOR_H
#define FLOW_MONITOR_H
/*******************************************************************************
 * Flow Monitor — Control Flow Checkpoint Verification (ISO 26262)
 *
 * Verifies that the main loop executes all expected checkpoints in order.
 * Also monitors actuator command reception deadline.
 ******************************************************************************/

#include <stdint.h>
#include <stdbool.h>

/* Checkpoint IDs (must be hit in order each loop iteration) */
typedef enum {
    CP_SENSOR_READ = 0,
    CP_E2E_ENCODE,
    CP_SECOC_ENCODE,
    CP_PUBLISH,
    CP_COUNT,
} flow_checkpoint_t;

/* Deadline for actuator command reception (ms) */
#define FLOW_ACTUATOR_DEADLINE_MS  10000  /* 10 seconds */

typedef struct {
    uint8_t  checkpoints_hit;     /* bitmask of checkpoints hit this cycle */
    uint32_t last_actuator_tick;  /* tick of last valid actuator message */
    uint32_t total_flow_errors;
    uint32_t total_deadline_misses;
    bool     deadline_active;     /* only active after first actuator received */
} flow_monitor_t;

void flow_init(flow_monitor_t *fm);

/* Mark a checkpoint as hit */
void flow_checkpoint(flow_monitor_t *fm, flow_checkpoint_t cp);

/* Verify all checkpoints were hit in this cycle. Returns true if OK.
 * Call at end of each publish loop iteration. Resets checkpoint mask. */
bool flow_verify_cycle(flow_monitor_t *fm);

/* Record actuator reception (resets deadline timer) */
void flow_actuator_received(flow_monitor_t *fm, uint32_t tick);

/* Check actuator deadline. Returns true if within deadline. */
bool flow_check_deadline(flow_monitor_t *fm, uint32_t current_tick);

/* Get error counts */
uint32_t flow_get_errors(const flow_monitor_t *fm);
uint32_t flow_get_deadline_misses(const flow_monitor_t *fm);

#endif /* FLOW_MONITOR_H */
