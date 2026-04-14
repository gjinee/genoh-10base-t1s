"""Tests for SafetyManager (Safety State Machine).

Test IDs correspond to FST-010~014 from functional_safety.md Section 9.2.
"""

import threading
import time

import pytest

from src.common.safety_types import FaultType, SafetyState, SAFE_ACTIONS
from src.master.dtc_manager import DTCManager
from src.master.safety_log import SafetyLog
from src.master.safety_manager import SafetyManager


class TestSafetyFSM:
    """Test Safety State Machine transitions."""

    def test_initial_state_normal(self):
        sm = SafetyManager()
        assert sm.state == SafetyState.NORMAL

    def test_normal_to_degraded_on_node_fault(self):
        """FST-010: Node offline triggers NORMAL → DEGRADED."""
        sm = SafetyManager()
        result = sm.notify_fault(FaultType.NODE_OFFLINE, source="node_1")
        assert result == SafetyState.DEGRADED

    def test_degraded_to_normal_on_recovery(self):
        """FST-011: Recovery triggers DEGRADED → NORMAL."""
        sm = SafetyManager()
        sm.notify_fault(FaultType.NODE_OFFLINE, source="node_1")
        assert sm.state == SafetyState.DEGRADED
        result = sm.notify_recovery(source="node_1")
        assert result == SafetyState.NORMAL

    def test_degraded_to_safe_state_on_multi_fault(self):
        """FST-012: ≥50% nodes offline → SAFE_STATE."""
        sm = SafetyManager(total_nodes=4)
        sm.notify_fault(FaultType.NODE_OFFLINE, source="node_1")
        assert sm.state == SafetyState.DEGRADED
        result = sm.notify_fault(FaultType.NODE_OFFLINE, source="node_2")
        assert result == SafetyState.SAFE_STATE

    def test_safe_state_actuator_actions(self):
        """FST-013: Verify safe actions are defined per actuator type."""
        sm = SafetyManager()
        headlight = sm.get_safe_action("led_headlight")
        assert headlight is not None
        assert headlight["state"] == "on"

        motor = sm.get_safe_action("motor_window")
        assert motor is not None
        assert motor["state"] == "stop"

    def test_fail_silent_blocks_output(self):
        """FST-014: FAIL_SILENT state blocks all output."""
        sm = SafetyManager(total_nodes=2)
        assert sm.is_output_allowed
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n2")
        assert sm.state == SafetyState.SAFE_STATE
        # Force FAIL_SILENT via direct transition
        sm._safe_state_timeout_handler()
        assert sm.state == SafetyState.FAIL_SILENT
        assert not sm.is_output_allowed

    def test_normal_stays_on_single_crc_failure(self):
        """Single CRC failure doesn't transition from NORMAL."""
        sm = SafetyManager()
        sm.notify_fault(FaultType.CRC_FAILURE, source="sensor_1")
        assert sm.state == SafetyState.NORMAL

    def test_normal_to_degraded_on_triple_crc_failure(self):
        """3 consecutive CRC failures from same source → DEGRADED."""
        sm = SafetyManager()
        for _ in range(3):
            sm.notify_fault(FaultType.CRC_FAILURE, source="sensor_1")
        assert sm.state == SafetyState.DEGRADED

    def test_state_change_callback_fires(self):
        """on_state_change callback is called on transition."""
        transitions = []
        sm = SafetyManager(on_state_change=lambda old, new: transitions.append((old, new)))
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert len(transitions) == 1
        assert transitions[0] == (SafetyState.NORMAL, SafetyState.DEGRADED)

    def test_fail_silent_to_normal_requires_reset(self):
        """FAIL_SILENT can only return to NORMAL via reset."""
        sm = SafetyManager(total_nodes=2)
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n2")
        sm._safe_state_timeout_handler()
        assert sm.state == SafetyState.FAIL_SILENT
        # Recovery does not work from FAIL_SILENT
        sm.notify_recovery(source="n1")
        sm.notify_recovery(source="n2")
        assert sm.state == SafetyState.FAIL_SILENT
        # Reset works
        sm.reset()
        assert sm.state == SafetyState.NORMAL

    def test_asil_d_timeout_goes_to_safe_state(self):
        """ASIL-D sensor timeout → immediate SAFE_STATE from DEGRADED."""
        sm = SafetyManager()
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED
        result = sm.notify_fault(
            FaultType.TIMEOUT, source="proximity",
            details={"asil": "ASIL-D"},
        )
        assert result == SafetyState.SAFE_STATE

    def test_logs_all_transitions(self, tmp_path):
        """Safety log receives entries on state transitions."""
        slog = SafetyLog(path=str(tmp_path / "safety.jsonl"))
        sm = SafetyManager(safety_log=slog)
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        events = slog.read_events(last_n=100)
        # Should have both the fault log and the transition log
        assert len(events) >= 2

    def test_dtc_set_on_fault(self, tmp_path):
        """DTC is stored when fault is reported."""
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        sm = SafetyManager(dtc_manager=dtc)
        sm.notify_fault(FaultType.CRC_FAILURE, source="s1")
        assert dtc.count > 0

    def test_plca_beacon_lost_degraded(self):
        """PLCA beacon loss → DEGRADED."""
        sm = SafetyManager()
        result = sm.notify_fault(FaultType.PLCA_BEACON_LOST, source="eth1")
        assert result == SafetyState.DEGRADED

    def test_watchdog_expired_safe_state(self):
        """Watchdog expiry → SAFE_STATE (from DEGRADED)."""
        sm = SafetyManager()
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")  # → DEGRADED
        result = sm.notify_fault(FaultType.WATCHDOG_EXPIRED, source="main")
        assert result == SafetyState.SAFE_STATE
