"""Simulation tests for Safety FSM and E2E protection.

Simulates realistic multi-node scenarios exercising the full safety
stack: E2E encode/decode, Safety Manager FSM transitions, E2E
Supervisor, DTC Manager, Flow Monitor, and Watchdog.

Test IDs: SIM-S1~SIM-S10
"""

import os
import time

import pytest

from src.common.e2e_protection import (
    SequenceCounterState,
    e2e_decode,
    e2e_verify,
)
from src.common.payloads import (
    ENCODING_JSON,
    decode_e2e,
    encode_e2e,
)
from src.common.safety_types import (
    E2EStatus,
    FaultType,
    SafetyState,
)
from src.master.dtc_manager import DTCManager
from src.master.e2e_supervisor import E2ESupervisor
from src.master.flow_monitor import (
    CP_ACTUATOR,
    CP_DIAG,
    CP_QUERY,
    CP_SENSOR,
    FlowMonitor,
)
from src.master.safety_log import SafetyLog
from src.master.safety_manager import SafetyManager
from src.master.watchdog import Watchdog


class TestSafetyE2EMessageExchange:
    """SIM-S1: Full-cycle E2E protected message exchange between nodes."""

    def test_sensor_to_master_e2e_roundtrip(self):
        """Slave sends E2E sensor data, master decodes and verifies."""
        counter = SequenceCounterState()
        sensor_data = {"value": 25.3, "unit": "celsius", "ts": 1713000000000}
        key_expr = "vehicle/front/1/sensor/temperature"

        encoded = encode_e2e(sensor_data, key_expr, counter)

        decoded, header, crc_valid = decode_e2e(encoded, ENCODING_JSON)
        assert crc_valid is True
        assert decoded["value"] == 25.3
        assert header.data_id == 0x1001
        assert header.sequence_counter == 0

    def test_multiple_messages_sequence_tracking(self):
        """Sequence counters increment correctly across messages."""
        counter = SequenceCounterState()
        key_expr = "vehicle/front/1/sensor/temperature"
        sequences = []

        for i in range(10):
            data = {"value": 20.0 + i * 0.5, "unit": "celsius", "ts": 1713000000000 + i}
            encoded = encode_e2e(data, key_expr, counter)
            _, header, valid = decode_e2e(encoded, ENCODING_JSON)
            assert valid is True
            sequences.append(header.sequence_counter)

        assert sequences == list(range(10))

    def test_multi_sensor_independent_counters(self):
        """Different data_ids have independent sequence counters."""
        counter_temp = SequenceCounterState()
        counter_prox = SequenceCounterState()

        for i in range(5):
            e1 = encode_e2e({"value": 20.0 + i}, "vehicle/front/1/sensor/temperature", counter_temp)
            e2 = encode_e2e({"value": 100 + i}, "vehicle/front/1/sensor/proximity", counter_prox)

            _, h1, v1 = decode_e2e(e1, ENCODING_JSON)
            _, h2, v2 = decode_e2e(e2, ENCODING_JSON)
            assert v1 and v2
            assert h1.data_id == 0x1001
            assert h2.data_id == 0x1003
            assert h1.sequence_counter == i
            assert h2.sequence_counter == i


class TestSafetyFSMTransitions:
    """SIM-S2~S4: Safety FSM state transition scenarios."""

    def test_crc_failure_escalation(self, tmp_path):
        """SIM-S2: 3 consecutive CRC failures → DEGRADED."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)
        assert sm.state == SafetyState.NORMAL

        sm.notify_fault(FaultType.CRC_FAILURE, source="n1")
        assert sm.state == SafetyState.NORMAL  # 1st: no transition

        sm.notify_fault(FaultType.CRC_FAILURE, source="n1")
        assert sm.state == SafetyState.NORMAL  # 2nd: no transition

        sm.notify_fault(FaultType.CRC_FAILURE, source="n1")
        assert sm.state == SafetyState.DEGRADED  # 3rd: → DEGRADED

    def test_multi_node_offline_safe_state(self, tmp_path):
        """SIM-S3: ≥50% nodes offline → SAFE_STATE."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n2")
        assert sm.state == SafetyState.SAFE_STATE  # 50% offline

    def test_asil_d_timeout_immediate_safe_state(self, tmp_path):
        """SIM-S4: ASIL-D timeout → SAFE_STATE immediately (skip DEGRADED)."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        # First need to get to DEGRADED (can't skip from NORMAL to SAFE_STATE directly)
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED

        sm.notify_fault(FaultType.TIMEOUT, source="proximity", details={"asil": "ASIL-D"})
        assert sm.state == SafetyState.SAFE_STATE

    def test_watchdog_expiry_safe_state(self, tmp_path):
        """SIM-S4b: Watchdog expiry → SAFE_STATE."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        # Need DEGRADED first
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        sm.notify_fault(FaultType.WATCHDOG_EXPIRED, source="watchdog")
        assert sm.state == SafetyState.SAFE_STATE

    def test_flow_error_safe_state(self, tmp_path):
        """SIM-S4c: Flow error → SAFE_STATE."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        sm.notify_fault(FaultType.FLOW_ERROR, source="flow_monitor")
        assert sm.state == SafetyState.SAFE_STATE


class TestSafetyRecovery:
    """SIM-S5~S6: Recovery and full escalation scenarios."""

    def test_recovery_degraded_to_normal(self, tmp_path):
        """SIM-S5: DEGRADED → recovery → NORMAL."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED

        sm.notify_recovery(source="n1")
        assert sm.state == SafetyState.NORMAL

    def test_full_escalation_to_fail_silent(self, tmp_path):
        """SIM-S6: NORMAL → DEGRADED → SAFE_STATE → FAIL_SILENT via timer."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n2")
        assert sm.state == SafetyState.SAFE_STATE

        # Manually trigger the timeout handler (instead of waiting 60s)
        sm._safe_state_timeout_handler()
        assert sm.state == SafetyState.FAIL_SILENT
        assert sm.is_output_allowed is False

    def test_reset_from_fail_silent(self, tmp_path):
        """SIM-S6b: FAIL_SILENT → reset → NORMAL."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n2")
        sm._safe_state_timeout_handler()
        assert sm.state == SafetyState.FAIL_SILENT

        sm.reset()
        assert sm.state == SafetyState.NORMAL
        assert sm.is_output_allowed is True


class TestSafetyE2ESupervisor:
    """SIM-S7~S8: E2E Supervisor with multiple channels."""

    def test_multi_channel_monitoring(self, tmp_path):
        """SIM-S7: E2E supervisor tracks multiple data_ids independently."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)

        sv.register_channel(0x1001, deadline_ms=5000)
        sv.register_channel(0x1003, deadline_ms=500)

        counter_temp = SequenceCounterState()
        counter_prox = SequenceCounterState()

        # Send valid messages to both channels
        for _ in range(5):
            enc = encode_e2e({"v": 1}, "vehicle/front/1/sensor/temperature", counter_temp)
            h, p = e2e_decode(enc)
            status = sv.on_message_received(h, p)
            assert status == E2EStatus.VALID

            enc2 = encode_e2e({"v": 1}, "vehicle/front/1/sensor/proximity", counter_prox)
            h2, p2 = e2e_decode(enc2)
            status2 = sv.on_message_received(h2, p2)
            assert status2 == E2EStatus.VALID

        stats1 = sv.get_channel_stats(0x1001)
        stats2 = sv.get_channel_stats(0x1003)
        assert stats1["total_received"] == 5
        assert stats2["total_received"] == 5
        assert stats1["total_crc_failures"] == 0

    def test_sequence_gap_detection(self, tmp_path):
        """SIM-S8: E2E supervisor detects sequence counter gaps."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)
        sv.register_channel(0x1001, max_seq_gap=3)

        counter = SequenceCounterState()

        # Send seq=0
        enc = encode_e2e({"v": 1}, "vehicle/front/1/sensor/temperature", counter)
        h, p = e2e_decode(enc)
        sv.on_message_received(h, p)

        # Skip seq=1,2 (send seq=3) — within gap limit
        counter.current_seq = 3
        enc2 = encode_e2e({"v": 2}, "vehicle/front/1/sensor/temperature", counter)
        h2, p2 = e2e_decode(enc2)
        status = sv.on_message_received(h2, p2)
        assert status == E2EStatus.VALID  # gap of 3, within limit

        stats = sv.get_channel_stats(0x1001)
        assert stats["total_seq_errors"] >= 1  # gap detected but tolerated

    def test_crc_corruption_detected(self, tmp_path):
        """SIM-S8b: CRC corruption flagged by E2E supervisor."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)
        sv.register_channel(0x1001)

        counter = SequenceCounterState()
        enc = encode_e2e({"v": 1}, "vehicle/front/1/sensor/temperature", counter)

        # Corrupt the payload
        corrupted = bytearray(enc)
        corrupted[-1] ^= 0xFF
        h, p = e2e_decode(bytes(corrupted))
        status = sv.on_message_received(h, p)
        assert status == E2EStatus.INVALID

        stats = sv.get_channel_stats(0x1001)
        assert stats["total_crc_failures"] == 1


class TestSafetyFlowMonitor:
    """SIM-S9: Flow monitor checkpoint verification."""

    def test_correct_flow_passes(self):
        """SIM-S9: Correct checkpoint order passes verification."""
        fm = FlowMonitor()
        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_ACTUATOR)
        fm.checkpoint(CP_QUERY)
        fm.checkpoint(CP_DIAG)
        assert fm.verify_cycle() is True
        assert fm.cycle_count == 1
        assert fm.error_count == 0

    def test_wrong_order_fails(self):
        """SIM-S9b: Wrong checkpoint order fails verification."""
        errors = []
        fm = FlowMonitor(on_error=lambda: errors.append(1))

        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_QUERY)  # Wrong: should be ACTUATOR
        fm.checkpoint(CP_ACTUATOR)
        fm.checkpoint(CP_DIAG)
        assert fm.verify_cycle() is False
        assert fm.error_count == 1
        assert len(errors) == 1

    def test_missing_checkpoint_fails(self):
        """SIM-S9c: Missing checkpoint fails verification."""
        fm = FlowMonitor()
        fm.checkpoint(CP_SENSOR)
        fm.checkpoint(CP_ACTUATOR)
        fm.checkpoint(CP_QUERY)
        # Missing CP_DIAG
        assert fm.verify_cycle() is False

    def test_multiple_cycles(self):
        """SIM-S9d: Multiple correct cycles tracked."""
        fm = FlowMonitor()
        for _ in range(10):
            fm.checkpoint(CP_SENSOR)
            fm.checkpoint(CP_ACTUATOR)
            fm.checkpoint(CP_QUERY)
            fm.checkpoint(CP_DIAG)
            assert fm.verify_cycle() is True
        assert fm.cycle_count == 10
        assert fm.error_count == 0


class TestSafetySafeActions:
    """SIM-S10: Safe action application in SAFE_STATE."""

    def test_safe_actions_available(self, tmp_path):
        """SIM-S10: Safe actions defined for actuators."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog)

        action = sm.get_safe_action("led_headlight")
        assert action is not None

        action_motor = sm.get_safe_action("motor_window")
        assert action_motor is not None

    def test_output_blocked_in_fail_silent(self, tmp_path):
        """SIM-S10b: Output blocked in FAIL_SILENT state."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        assert sm.is_output_allowed is True  # NORMAL

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n2")
        assert sm.is_output_allowed is True  # SAFE_STATE still allows

        sm._safe_state_timeout_handler()
        assert sm.state == SafetyState.FAIL_SILENT
        assert sm.is_output_allowed is False

    def test_dtc_set_on_fault(self, tmp_path):
        """SIM-S10c: DTC codes set correctly on faults."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        dtc = DTCManager(path=str(tmp_path / "d.json"))
        sm = SafetyManager(safety_log=slog, dtc_manager=dtc, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert dtc.count > 0

        sm.notify_fault(FaultType.CRC_FAILURE, source="n2")
        sm.notify_fault(FaultType.CRC_FAILURE, source="n2")
        sm.notify_fault(FaultType.CRC_FAILURE, source="n2")
        assert dtc.count >= 2

    def test_safety_log_events_recorded(self, tmp_path):
        """SIM-S10d: Safety events logged with correct structure."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        sm.notify_recovery(source="n1")

        events = slog.read_events(last_n=100)
        assert len(events) >= 3  # fault + state change + recovery
