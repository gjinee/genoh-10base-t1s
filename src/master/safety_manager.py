"""Safety State Machine for functional safety management (ISO 26262).

Implements the Safety FSM (NORMAL → DEGRADED → SAFE_STATE → FAIL_SILENT)
with transition logic, fault counting, and safe action definitions.
See functional_safety.md Section 3.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from src.common.safety_types import (
    DTC_CODES,
    SAFE_ACTIONS,
    FaultType,
    SafetyEventType,
    SafetyLogSeverity,
    SafetyState,
)

logger = logging.getLogger(__name__)

# Thresholds for state transitions
CRC_FAILURE_THRESHOLD = 3  # Consecutive CRC failures → DEGRADED
OFFLINE_PERCENT_THRESHOLD = 50  # % nodes offline → SAFE_STATE
SAFE_STATE_TIMEOUT_SEC = 60.0  # No recovery → FAIL_SILENT


class SafetyManager:
    """Safety State Machine managing system-wide safety behavior.

    State transitions (Section 3.2):
      NORMAL → DEGRADED:  Single node fault, consecutive CRC failures, PLCA lost
      DEGRADED → NORMAL:  All faults recovered
      DEGRADED → SAFE_STATE: Multiple node faults (≥50%), ASIL-D timeout
      SAFE_STATE → NORMAL: Full recovery confirmed (manual approval needed)
      SAFE_STATE → FAIL_SILENT: No recovery within 60 seconds
      FAIL_SILENT → NORMAL: System restart only
    """

    def __init__(
        self,
        safety_log=None,
        dtc_manager=None,
        total_nodes: int = 8,
        on_state_change: Callable[[SafetyState, SafetyState], None] | None = None,
    ):
        self._state = SafetyState.NORMAL
        self._lock = threading.Lock()
        self._safety_log = safety_log
        self._dtc_manager = dtc_manager
        self._total_nodes = total_nodes
        self._on_state_change = on_state_change

        # Fault tracking
        self._offline_nodes: set[str] = set()
        self._crc_failure_counts: dict[str, int] = {}
        self._safe_state_entry_time: float | None = None
        self._safe_state_timer: threading.Timer | None = None

    @property
    def state(self) -> SafetyState:
        with self._lock:
            return self._state

    @property
    def offline_nodes(self) -> set[str]:
        with self._lock:
            return set(self._offline_nodes)

    def notify_fault(
        self,
        fault_type: FaultType,
        source: str = "",
        details: dict | None = None,
    ) -> SafetyState:
        """Report a detected fault to the safety manager.

        Evaluates the fault against transition rules and updates
        the safety state accordingly.

        Returns:
            The safety state after processing the fault.
        """
        with self._lock:
            old_state = self._state
            details = details or {}

            if fault_type == FaultType.NODE_OFFLINE:
                self._offline_nodes.add(source)
                self._handle_node_fault(source, details)
            elif fault_type == FaultType.CRC_FAILURE:
                self._handle_crc_failure(source, details)
            elif fault_type == FaultType.TIMEOUT:
                self._handle_timeout(source, details)
            elif fault_type == FaultType.PLCA_BEACON_LOST:
                self._transition_to(SafetyState.DEGRADED, fault_type, source, details)
            elif fault_type in (FaultType.FLOW_ERROR, FaultType.WATCHDOG_EXPIRED):
                self._transition_to(SafetyState.SAFE_STATE, fault_type, source, details)
            elif fault_type == FaultType.SENSOR_PLAUSIBILITY:
                self._handle_sensor_plausibility(source, details)
            else:
                self._transition_to(SafetyState.DEGRADED, fault_type, source, details)

            # Log and DTC
            self._log_fault(fault_type, source, details)
            self._set_dtc_for_fault(fault_type)

            return self._state

    def notify_recovery(self, source: str = "") -> SafetyState:
        """Report that a previously faulted component has recovered.

        Returns:
            The safety state after processing the recovery.
        """
        with self._lock:
            self._offline_nodes.discard(source)
            self._crc_failure_counts.pop(source, None)

            if self._state == SafetyState.DEGRADED:
                if not self._offline_nodes and not self._crc_failure_counts:
                    self._transition_to(
                        SafetyState.NORMAL,
                        FaultType.NODE_OFFLINE,
                        source,
                        {"action": "recovery"},
                    )
            elif self._state == SafetyState.SAFE_STATE:
                if not self._offline_nodes:
                    self._cancel_safe_state_timer()
                    self._transition_to(
                        SafetyState.NORMAL,
                        FaultType.NODE_OFFLINE,
                        source,
                        {"action": "full_recovery"},
                    )

            if self._safety_log:
                self._safety_log.log_event(
                    severity=SafetyLogSeverity.SAFETY_INFO,
                    event=SafetyEventType.NODE_ONLINE,
                    source=source,
                    safety_state=self._state,
                )

            return self._state

    def get_safe_action(self, actuator_key: str) -> dict | None:
        """Get the safe action for an actuator type.

        Args:
            actuator_key: Key from SAFE_ACTIONS (e.g., "led_headlight", "motor_window")

        Returns:
            Safe action dict or None if not defined.
        """
        return SAFE_ACTIONS.get(actuator_key)

    @property
    def is_output_allowed(self) -> bool:
        """Whether actuator output is allowed in current state."""
        return self._state != SafetyState.FAIL_SILENT

    def reset(self) -> None:
        """Reset to NORMAL state (system restart equivalent)."""
        with self._lock:
            old_state = self._state
            self._cancel_safe_state_timer()
            self._state = SafetyState.NORMAL
            self._offline_nodes.clear()
            self._crc_failure_counts.clear()
            self._safe_state_entry_time = None
            if old_state != SafetyState.NORMAL and self._on_state_change:
                self._on_state_change(old_state, SafetyState.NORMAL)

    # --- Internal transition logic ---

    def _handle_node_fault(self, source: str, details: dict) -> None:
        offline_pct = (len(self._offline_nodes) / self._total_nodes) * 100
        if self._state == SafetyState.NORMAL:
            self._transition_to(SafetyState.DEGRADED, FaultType.NODE_OFFLINE, source, details)
        if offline_pct >= OFFLINE_PERCENT_THRESHOLD:
            self._transition_to(SafetyState.SAFE_STATE, FaultType.NODE_OFFLINE, source, details)

    def _handle_crc_failure(self, source: str, details: dict) -> None:
        count = self._crc_failure_counts.get(source, 0) + 1
        self._crc_failure_counts[source] = count
        if count >= CRC_FAILURE_THRESHOLD and self._state == SafetyState.NORMAL:
            self._transition_to(SafetyState.DEGRADED, FaultType.CRC_FAILURE, source, details)

    def _handle_timeout(self, source: str, details: dict) -> None:
        asil = details.get("asil", "")
        if asil == "ASIL-D":
            self._transition_to(SafetyState.SAFE_STATE, FaultType.TIMEOUT, source, details)
        elif self._state == SafetyState.NORMAL:
            self._transition_to(SafetyState.DEGRADED, FaultType.TIMEOUT, source, details)

    def _handle_sensor_plausibility(self, source: str, details: dict) -> None:
        if self._state == SafetyState.NORMAL:
            self._transition_to(SafetyState.DEGRADED, FaultType.SENSOR_PLAUSIBILITY, source, details)

    def _transition_to(
        self,
        new_state: SafetyState,
        fault_type: FaultType,
        source: str,
        details: dict,
    ) -> None:
        """Execute state transition if valid."""
        old_state = self._state

        # Only allow valid transitions
        valid = self._is_valid_transition(old_state, new_state)
        if not valid:
            return

        self._state = new_state

        # Start SAFE_STATE → FAIL_SILENT timer
        if new_state == SafetyState.SAFE_STATE:
            self._safe_state_entry_time = time.monotonic()
            self._start_safe_state_timer()

        if old_state != new_state:
            logger.warning(
                "Safety state: %s → %s (fault=%s, source=%s)",
                old_state.value, new_state.value, fault_type.value, source,
            )
            if self._on_state_change:
                self._on_state_change(old_state, new_state)

            if self._safety_log:
                event_type = self._state_to_event_type(new_state)
                self._safety_log.log_event(
                    severity=SafetyLogSeverity.SAFETY_CRITICAL
                    if new_state in (SafetyState.SAFE_STATE, SafetyState.FAIL_SILENT)
                    else SafetyLogSeverity.SAFETY_WARNING,
                    event=event_type,
                    source=source,
                    details=details,
                    safety_state=new_state,
                )

    def _is_valid_transition(self, old: SafetyState, new: SafetyState) -> bool:
        """Check if a state transition is allowed."""
        if old == new:
            return False
        valid_transitions = {
            SafetyState.NORMAL: {SafetyState.DEGRADED},
            SafetyState.DEGRADED: {SafetyState.NORMAL, SafetyState.SAFE_STATE},
            SafetyState.SAFE_STATE: {SafetyState.NORMAL, SafetyState.FAIL_SILENT},
            SafetyState.FAIL_SILENT: {SafetyState.NORMAL},  # restart only
        }
        return new in valid_transitions.get(old, set())

    def _start_safe_state_timer(self) -> None:
        self._cancel_safe_state_timer()
        self._safe_state_timer = threading.Timer(
            SAFE_STATE_TIMEOUT_SEC,
            self._safe_state_timeout_handler,
        )
        self._safe_state_timer.daemon = True
        self._safe_state_timer.start()

    def _cancel_safe_state_timer(self) -> None:
        if self._safe_state_timer:
            self._safe_state_timer.cancel()
            self._safe_state_timer = None

    def _safe_state_timeout_handler(self) -> None:
        with self._lock:
            if self._state == SafetyState.SAFE_STATE:
                self._transition_to(
                    SafetyState.FAIL_SILENT,
                    FaultType.TIMEOUT,
                    "safety_manager",
                    {"reason": "no_recovery_within_timeout"},
                )

    def _log_fault(self, fault_type: FaultType, source: str, details: dict) -> None:
        if not self._safety_log:
            return
        self._safety_log.log_event(
            severity=SafetyLogSeverity.SAFETY_WARNING,
            event=fault_type.value,
            source=source,
            details=details,
            safety_state=self._state,
        )

    def _set_dtc_for_fault(self, fault_type: FaultType) -> None:
        if not self._dtc_manager:
            return
        dtc_map = {
            FaultType.CRC_FAILURE: DTC_CODES["e2e_crc_failure"],
            FaultType.SEQ_ERROR: DTC_CODES["e2e_seq_error"],
            FaultType.TIMEOUT: DTC_CODES["e2e_timeout"],
            FaultType.NODE_OFFLINE: DTC_CODES["node_comm_lost"],
            FaultType.PLCA_BEACON_LOST: DTC_CODES["bus_general_error"],
            FaultType.WATCHDOG_EXPIRED: DTC_CODES["master_internal_error"],
            FaultType.SENSOR_PLAUSIBILITY: DTC_CODES["sensor_plausibility"],
            FaultType.FLOW_ERROR: DTC_CODES["master_internal_error"],
        }
        dtc_code = dtc_map.get(fault_type)
        if dtc_code is not None:
            self._dtc_manager.set_dtc(dtc_code, fault_type.value)

    @staticmethod
    def _state_to_event_type(state: SafetyState) -> str:
        return {
            SafetyState.NORMAL: SafetyEventType.NORMAL_RESTORED.value,
            SafetyState.DEGRADED: SafetyEventType.DEGRADED_ENTER.value,
            SafetyState.SAFE_STATE: SafetyEventType.SAFE_STATE_ENTER.value,
            SafetyState.FAIL_SILENT: SafetyEventType.FAIL_SILENT_ENTER.value,
        }.get(state, "UNKNOWN")
