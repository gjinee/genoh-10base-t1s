"""Simulation tests for Fault Injection scenarios.

Simulates node failures, network disruptions, and data corruption
to verify safety and security responses.

Test IDs: SIM-F1~SIM-F8
"""

import os
import time

import pytest

from src.common.e2e_protection import (
    SequenceCounterState,
    e2e_decode,
)
from src.common.payloads import ENCODING_JSON, decode_e2e, encode_e2e
from src.common.safety_types import E2EStatus, FaultType, SafetyState
from src.master.dtc_manager import DTCManager
from src.master.e2e_supervisor import E2ESupervisor
from src.master.safety_log import SafetyLog
from src.master.safety_manager import SafetyManager
from src.master.ids_engine import IDSEngine
from src.master.security_log import SecurityLog
from src.common.security_types import IDSRuleID


class TestNodeKillFault:
    """SIM-F1: Node goes offline mid-stream."""

    def test_single_node_offline_degraded(self, tmp_path):
        """SIM-F1: Single node kill → DEGRADED state + DTC."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        dtc = DTCManager(path=str(tmp_path / "d.json"))
        sm = SafetyManager(safety_log=slog, dtc_manager=dtc, total_nodes=4)
        sv = E2ESupervisor(safety_manager=sm, dtc_manager=dtc, safety_log=slog)

        counter = SequenceCounterState()
        sv.register_channel(0x1001, deadline_ms=100)

        # Node sends 3 valid messages
        for _ in range(3):
            enc = encode_e2e({"v": 1}, "vehicle/front/1/sensor/temperature", counter)
            h, p = e2e_decode(enc)
            sv.on_message_received(h, p)

        # Node goes offline → master detects
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED
        assert dtc.count > 0

    def test_cascading_node_failure(self, tmp_path):
        """SIM-F1b: Multiple nodes fail sequentially → SAFE_STATE."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n2")
        assert sm.state == SafetyState.SAFE_STATE

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n3")
        assert sm.state == SafetyState.SAFE_STATE  # Already in SAFE_STATE


class TestNetworkDisconnect:
    """SIM-F2: Network disconnect → timeout → safe state."""

    def test_timeout_after_disconnect(self, tmp_path):
        """SIM-F2: No messages → E2E timeout → safety fault."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)

        # Register channel with very short deadline for test
        sv.register_channel(0x1001, deadline_ms=1)

        # Wait for timeout
        time.sleep(0.01)
        timed_out = sv.check_timeouts()

        assert 0x1001 in timed_out
        stats = sv.get_channel_stats(0x1001)
        assert stats["total_timeouts"] >= 1

    def test_plca_beacon_loss(self, tmp_path):
        """SIM-F2b: PLCA beacon lost → DEGRADED."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(FaultType.PLCA_BEACON_LOST, source="plca")
        assert sm.state == SafetyState.DEGRADED


class TestCRCCorruptionBurst:
    """SIM-F3: Burst of CRC-corrupted messages."""

    def test_crc_burst_triggers_degraded(self, tmp_path):
        """SIM-F3: Consecutive CRC failures from same source → DEGRADED."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        dtc = DTCManager(path=str(tmp_path / "d.json"))
        sm = SafetyManager(safety_log=slog, dtc_manager=dtc, total_nodes=4)
        sv = E2ESupervisor(safety_manager=sm, dtc_manager=dtc, safety_log=slog)
        sv.register_channel(0x1001)

        counter = SequenceCounterState()

        # Send 5 corrupted messages
        for _ in range(5):
            enc = encode_e2e({"v": 1}, "vehicle/front/1/sensor/temperature", counter)
            corrupted = bytearray(enc)
            corrupted[-1] ^= 0xFF
            h, p = e2e_decode(bytes(corrupted))
            sv.on_message_received(h, p)

        stats = sv.get_channel_stats(0x1001)
        assert stats["total_crc_failures"] == 5
        assert stats["status"] == E2EStatus.ERROR.value  # After 3 consecutive
        assert sm.state == SafetyState.DEGRADED

    def test_valid_after_corruption_recovers(self, tmp_path):
        """SIM-F3b: Valid messages after corruption clear failure counter."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)
        sv.register_channel(0x1001)

        counter = SequenceCounterState()

        # 2 corrupted (below threshold)
        for _ in range(2):
            enc = encode_e2e({"v": 1}, "vehicle/front/1/sensor/temperature", counter)
            corrupted = bytearray(enc)
            corrupted[-1] ^= 0xFF
            h, p = e2e_decode(bytes(corrupted))
            sv.on_message_received(h, p)

        # Then valid message resets counter
        enc = encode_e2e({"v": 1}, "vehicle/front/1/sensor/temperature", counter)
        h, p = e2e_decode(enc)
        status = sv.on_message_received(h, p)
        assert status == E2EStatus.VALID


class TestSequenceJump:
    """SIM-F4: Sequence counter jump scenarios."""

    def test_large_sequence_gap_error(self, tmp_path):
        """SIM-F4: Sequence gap > max → ERROR status."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)
        sv.register_channel(0x1001, max_seq_gap=3)

        counter = SequenceCounterState()

        # Send seq=0
        enc = encode_e2e({"v": 1}, "vehicle/front/1/sensor/temperature", counter)
        h, p = e2e_decode(enc)
        sv.on_message_received(h, p)

        # Jump to seq=10 (gap of 10, exceeds max_gap=3)
        counter.current_seq = 10
        enc2 = encode_e2e({"v": 2}, "vehicle/front/1/sensor/temperature", counter)
        h2, p2 = e2e_decode(enc2)
        status = sv.on_message_received(h2, p2)
        assert status == E2EStatus.INVALID

        stats = sv.get_channel_stats(0x1001)
        assert stats["total_seq_errors"] >= 1

    def test_duplicate_sequence_ignored(self, tmp_path):
        """SIM-F4b: Duplicate sequence number is silently ignored."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)
        sv.register_channel(0x1001)

        counter = SequenceCounterState()

        # Send seq=0
        enc = encode_e2e({"v": 1}, "vehicle/front/1/sensor/temperature", counter)
        h, p = e2e_decode(enc)
        sv.on_message_received(h, p)

        # Replay seq=0 (duplicate)
        counter2 = SequenceCounterState()
        enc2 = encode_e2e({"v": 2}, "vehicle/front/1/sensor/temperature", counter2)
        h2, p2 = e2e_decode(enc2)
        sv.on_message_received(h2, p2)

        stats = sv.get_channel_stats(0x1001)
        assert stats["total_received"] == 2  # Both received but duplicate handled


class TestSimultaneousMultiNodeOffline:
    """SIM-F5: Simultaneous multi-node offline → IDS-008."""

    def test_three_nodes_offline_ids_alert(self, tmp_path):
        """SIM-F5: ≥3 nodes offline → IDS-008 + safety SAFE_STATE."""
        slog_sec = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        slog_saf = SafetyLog(path=str(tmp_path / "saf.jsonl"))
        ids = IDSEngine(security_log=slog_sec)
        sm = SafetyManager(safety_log=slog_saf, total_nodes=6)

        # Nodes go offline
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        ids.report_node_offline("n1")

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n2")
        ids.report_node_offline("n2")

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n3")
        alerts = ids.report_node_offline("n3")

        # IDS-008 triggered
        assert any(a.rule_id == IDSRuleID.IDS_008.value for a in alerts)
        # Safety state escalated
        assert sm.state == SafetyState.SAFE_STATE

    def test_sensor_plausibility_fault(self, tmp_path):
        """SIM-F5b: Sensor plausibility violation → DEGRADED."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(
            FaultType.SENSOR_PLAUSIBILITY,
            source="n1",
            details={"sensor": "temperature", "value": 999.9, "max": 45.0},
        )
        assert sm.state == SafetyState.DEGRADED


class TestCombinedSafetySecurityFaults:
    """SIM-F6~F8: Combined safety + security fault scenarios."""

    def test_mac_and_crc_simultaneous_failure(self, tmp_path):
        """SIM-F6: MAC + CRC both fail → IDS-010 + safety CRC fault."""
        slog_sec = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        slog_saf = SafetyLog(path=str(tmp_path / "saf.jsonl"))
        ids = IDSEngine(security_log=slog_sec)
        sm = SafetyManager(safety_log=slog_saf, total_nodes=4)

        # IDS detects combined failure
        alerts = ids.check_message(
            source_node="n1",
            key_expr="vehicle/front/1/sensor/temperature",
            payload_size=50,
            mac_valid=False,
            crc_valid=False,
        )
        assert any(a.rule_id == IDSRuleID.IDS_010.value for a in alerts)

        # Safety side: 3 CRC failures → DEGRADED
        for _ in range(3):
            sm.notify_fault(FaultType.CRC_FAILURE, source="n1")
        assert sm.state == SafetyState.DEGRADED

    def test_attack_followed_by_node_kill(self, tmp_path):
        """SIM-F7: Attack (flooding) then node kill → combined response."""
        slog_sec = SecurityLog(path=str(tmp_path / "sec.jsonl"))
        slog_saf = SafetyLog(path=str(tmp_path / "saf.jsonl"))
        ids = IDSEngine(security_log=slog_sec)
        sm = SafetyManager(safety_log=slog_saf, total_nodes=4)

        # Flooding attack
        for _ in range(60):
            ids._rate_limiter.record("attacker")
        alerts = ids.check_message(
            "attacker", "vehicle/front/1/sensor/temperature", 50,
        )
        assert any(a.rule_id == IDSRuleID.IDS_002.value for a in alerts)

        # Node kill follows
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n2")
        assert sm.state == SafetyState.SAFE_STATE

        # Security log chain still valid
        assert slog_sec.verify_chain() is True

    def test_recovery_from_combined_faults(self, tmp_path):
        """SIM-F8: Recovery after combined safety+security faults."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        # Escalate to DEGRADED
        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED

        # Recover
        sm.notify_recovery(source="n1")
        assert sm.state == SafetyState.NORMAL
        assert sm.is_output_allowed is True
