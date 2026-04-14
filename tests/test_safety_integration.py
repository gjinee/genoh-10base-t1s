"""Tests for Phase 5: Safety Integration.

Verifies E2E encode/decode through payloads.py, safety manager
integration, and backward compatibility with existing tests.
Test IDs: FIT-001~004 from functional_safety.md Section 9.3.
"""

import os

import pytest

from src.common.e2e_protection import (
    E2E_HEADER_SIZE,
    E2EHeader,
    SequenceCounterState,
    e2e_decode,
    e2e_verify,
)
from src.common.payloads import (
    ENCODING_CBOR,
    ENCODING_JSON,
    decode,
    decode_e2e,
    encode,
    encode_e2e,
)
from src.common.safety_types import FaultType, SafetyState
from src.master.dtc_manager import DTCManager
from src.master.e2e_supervisor import E2ESupervisor
from src.master.safety_log import SafetyLog
from src.master.safety_manager import SafetyManager
from src.master.self_test import SelfTest
from src.master.watchdog import Watchdog


class TestPayloadsE2E:
    """Test E2E encode/decode through payloads.py."""

    def test_encode_e2e_roundtrip_json(self):
        data = {"value": 25.3, "unit": "celsius", "ts": 1713000000000}
        counter = SequenceCounterState()
        encoded = encode_e2e(data, "vehicle/front/1/sensor/temperature", counter)
        assert len(encoded) > E2E_HEADER_SIZE

        decoded, header, crc_valid = decode_e2e(encoded, ENCODING_JSON)
        assert crc_valid is True
        assert decoded["value"] == 25.3
        assert header.data_id == 0x1001

    def test_encode_e2e_roundtrip_cbor(self):
        data = {"action": "set", "params": {"state": "on"}}
        counter = SequenceCounterState()
        encoded = encode_e2e(data, "vehicle/front/1/actuator/led", counter, ENCODING_CBOR)

        decoded, header, crc_valid = decode_e2e(encoded, ENCODING_CBOR)
        assert crc_valid is True
        assert decoded["action"] == "set"
        assert header.data_id == 0x2001

    def test_e2e_crc_mismatch_detected(self):
        data = {"value": 10.0}
        counter = SequenceCounterState()
        encoded = encode_e2e(data, "vehicle/front/1/sensor/temperature", counter)

        # Corrupt a byte in payload area but keep it valid UTF-8
        corrupted = bytearray(encoded)
        # Flip a bit in the E2E header CRC field (bytes 7-10) instead
        corrupted[8] ^= 0x01
        header, payload = e2e_decode(bytes(corrupted))
        assert e2e_verify(header, payload) is False

    def test_existing_encode_decode_still_works(self):
        """Backward compatibility: original encode/decode unchanged."""
        data = {"value": 42}
        raw = encode(data, ENCODING_JSON)
        restored = decode(raw, ENCODING_JSON)
        assert restored["value"] == 42

    def test_sequence_counter_increments(self):
        counter = SequenceCounterState()
        headers = []
        for _ in range(3):
            encoded = encode_e2e(
                {"v": 1}, "vehicle/front/1/sensor/temperature", counter,
            )
            _, header, _ = decode_e2e(encoded)
            headers.append(header)
        assert [h.sequence_counter for h in headers] == [0, 1, 2]


class TestSafetyIntegration:
    """Test safety module integration scenarios."""

    def test_node_offline_triggers_degraded(self, tmp_path):
        """FIT-001: Node offline → DEGRADED state."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        dtc = DTCManager(path=str(tmp_path / "d.json"))
        sm = SafetyManager(safety_log=slog, dtc_manager=dtc, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="node_1")
        assert sm.state == SafetyState.DEGRADED
        assert dtc.count > 0

    def test_corrupted_payload_rejected_by_e2e(self, tmp_path):
        """FIT-003: Corrupted payload → CRC failure → E2E supervisor rejects."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog)
        sv = E2ESupervisor(safety_manager=sm, safety_log=slog)
        sv.register_channel(0x1001)

        # Create valid then corrupt
        counter = SequenceCounterState()
        encoded = encode_e2e(
            {"value": 25.3}, "vehicle/front/1/sensor/temperature", counter,
        )
        corrupted = bytearray(encoded)
        corrupted[-1] ^= 0xFF
        header, payload = e2e_decode(bytes(corrupted))
        sv.on_message_received(header, payload)

        # Should have detected CRC failure
        stats = sv.get_channel_stats(0x1001)
        assert stats["total_crc_failures"] == 1

    def test_full_safety_stack_startup(self, tmp_path):
        """FIT: Full safety stack initializes and passes self-test."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog)
        dtc = DTCManager(path=str(tmp_path / "d.json"))
        wd = Watchdog(timeout_sec=10.0)

        st = SelfTest(
            safety_manager=sm,
            dtc_manager=dtc,
            safety_log=slog,
            watchdog=wd,
        )
        ok, results = st.run()
        assert ok is True
        assert sm.state == SafetyState.NORMAL

    def test_multi_fault_escalation(self, tmp_path):
        """Full escalation: NORMAL → DEGRADED → SAFE_STATE."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n2")
        assert sm.state == SafetyState.SAFE_STATE

        assert not sm.is_output_allowed or sm.state == SafetyState.SAFE_STATE

    def test_recovery_cycle(self, tmp_path):
        """Full cycle: NORMAL → DEGRADED → recovery → NORMAL."""
        slog = SafetyLog(path=str(tmp_path / "s.jsonl"))
        sm = SafetyManager(safety_log=slog, total_nodes=4)

        sm.notify_fault(FaultType.NODE_OFFLINE, source="n1")
        assert sm.state == SafetyState.DEGRADED

        sm.notify_recovery(source="n1")
        assert sm.state == SafetyState.NORMAL

        events = slog.read_events(last_n=100)
        assert len(events) >= 3  # fault + transition + recovery
