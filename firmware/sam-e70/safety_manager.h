#ifndef SAFETY_MANAGER_H
#define SAFETY_MANAGER_H
/*******************************************************************************
 * Safety Manager — ASIL-D Functional Safety State Machine
 *
 * States: NORMAL → DEGRADED → SAFE_STATE → FAIL_SILENT
 * ISO 26262:2018 Part 6 compliant
 ******************************************************************************/

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    SAFETY_NORMAL = 0,
    SAFETY_DEGRADED,
    SAFETY_SAFE_STATE,
    SAFETY_FAIL_SILENT,
} safety_state_t;

typedef enum {
    FAULT_CRC_FAILURE = 0,
    FAULT_SEQ_ERROR,
    FAULT_MAC_FAILURE,
    FAULT_REPLAY,
    FAULT_FLOOD,
    FAULT_FLOW,
    FAULT_TIMEOUT,
    FAULT_WATCHDOG,
    FAULT_SELF_TEST,
    FAULT_TYPE_COUNT,
} fault_type_t;

/* ASIL-D thresholds */
#define ASILD_CRC_THRESHOLD      1    /* 1 CRC failure → DEGRADED */
#define ASILD_SEQ_THRESHOLD      1    /* 1 seq error → DEGRADED */
#define ASILD_MAC_THRESHOLD      1    /* 1 MAC failure → DEGRADED */
#define ASILD_DEGRADED_TIMEOUT  30000 /* 30s in DEGRADED → SAFE_STATE (ms) */
#define ASILD_RECOVERY_COUNT    10    /* 10 consecutive OK → NORMAL */

typedef struct {
    safety_state_t state;
    uint32_t fault_counts[FAULT_TYPE_COUNT];
    uint32_t total_faults;
    uint32_t consecutive_ok;
    uint32_t degraded_enter_tick;  /* tick when entered DEGRADED */
    bool     self_test_passed;
} safety_manager_t;

/* Initialize safety manager */
void safety_init(safety_manager_t *sm);

/* Run boot self-test. Returns true if all checks pass. */
bool safety_self_test(safety_manager_t *sm);

/* Report a fault — may trigger state transition */
void safety_report_fault(safety_manager_t *sm, fault_type_t fault);

/* Report successful message — may recover from DEGRADED */
void safety_report_ok(safety_manager_t *sm);

/* Check time-based transitions (call periodically) */
void safety_tick(safety_manager_t *sm, uint32_t current_tick);

/* Get current state */
safety_state_t safety_get_state(const safety_manager_t *sm);

/* Execute safe action: turn off all actuators */
void safety_execute_safe_action(void);

/* Is actuator control allowed? */
bool safety_actuator_allowed(const safety_manager_t *sm);

/* Periodic self-test (call every ~10 seconds). Returns true if OK. */
bool safety_periodic_test(safety_manager_t *sm);

#endif /* SAFETY_MANAGER_H */
