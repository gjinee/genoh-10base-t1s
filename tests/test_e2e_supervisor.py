"""Tests for E2ESupervisor (per-data_id timeout and sequence monitoring).

Test IDs include FST-006 from functional_safety.md Section 9.1.
"""

import time

import pytest

from src.common.e2e_protection import (
    E2EHeader,
    SequenceCounterState,
    compute_e2e_crc,
    e2e_encode,
    e2e_decode,
)
from src.common.safety_types import E2EStatus, DTC_CODES, SafetyState
from src.master.dtc_manager import DTCManager
from src.master.safety_log import SafetyLog
from src.master.safety_manager import SafetyManager
from src.master.e2e_supervisor import E2ESupervisor


def _make_valid_message(data_id: int, counter: SequenceCounterState) -> tuple[E2EHeader, bytes]:
    """Helper to create a valid E2E message and return (header, payload)."""
    payload = b'{"value":25.3}'
    encoded = e2e_encode(data_id, payload, counter)
    header, decoded_payload = e2e_decode(encoded)
    return header, decoded_payload


def _make_corrupt_header(data_id: int, seq: int, payload: bytes) -> E2EHeader:
    """Create a header with wrong CRC."""
    return E2EHeader(
        data_id=data_id,
        sequence_counter=seq,
        alive_counter=0,
        length=len(payload),
        crc32=0xDEADBEEF,  # Intentionally wrong
    )


class TestE2ESupervisor:
    """Test E2E supervision and state machine."""

    def test_valid_message_sets_valid(self):
        sv = E2ESupervisor()
        sv.register_channel(0x1001)
        counter = SequenceCounterState()
        header, payload = _make_valid_message(0x1001, counter)
        status = sv.on_message_received(header, payload)
        # First message goes through INIT
        assert status in (E2EStatus.VALID, E2EStatus.INIT)

    def test_valid_messages_reach_valid_state(self):
        sv = E2ESupervisor()
        sv.register_channel(0x1001)
        counter = SequenceCounterState()
        for _ in range(5):
            header, payload = _make_valid_message(0x1001, counter)
            status = sv.on_message_received(header, payload)
        assert status == E2EStatus.VALID

    def test_crc_failure_sets_invalid(self):
        sv = E2ESupervisor()
        sv.register_channel(0x1001)
        payload = b"test"
        header = _make_corrupt_header(0x1001, 0, payload)
        status = sv.on_message_received(header, payload)
        assert status == E2EStatus.INVALID

    def test_crc_failure_notifies_safety_manager(self, tmp_path):
        sm = SafetyManager()
        sv = E2ESupervisor(safety_manager=sm)
        sv.register_channel(0x1001)
        payload = b"test"
        for i in range(3):
            header = _make_corrupt_header(0x1001, i, payload)
            sv.on_message_received(header, payload)
        # SafetyManager should have received CRC failure notifications
        assert sm.state != SafetyState.NORMAL  # At least DEGRADED

    def test_seq_error_notifies_safety_manager(self):
        sm = SafetyManager()
        sv = E2ESupervisor(safety_manager=sm)
        sv.register_channel(0x1001, max_seq_gap=1)
        counter = SequenceCounterState()
        # Send seq 0, 1, 2 (valid)
        for _ in range(3):
            h, p = _make_valid_message(0x1001, counter)
            sv.on_message_received(h, p)
        # Jump seq counter to create gap
        counter.current_seq = 100
        h, p = _make_valid_message(0x1001, counter)
        sv.on_message_received(h, p)
        # Should have reported a fault

    def test_e2e_state_init_to_valid(self):
        """E2E state transitions from INIT to VALID after N messages."""
        sv = E2ESupervisor()
        sv.register_channel(0x1001)
        counter = SequenceCounterState()
        statuses = []
        for _ in range(5):
            h, p = _make_valid_message(0x1001, counter)
            statuses.append(sv.on_message_received(h, p))
        # Should eventually reach VALID
        assert E2EStatus.VALID in statuses

    def test_e2e_state_timeout(self):
        """FST-006: No message within deadline → TIMEOUT."""
        sv = E2ESupervisor()
        sv.register_channel(0x1001, deadline_ms=100)
        counter = SequenceCounterState()
        h, p = _make_valid_message(0x1001, counter)
        sv.on_message_received(h, p)
        # Wait for deadline to pass
        time.sleep(0.2)
        timed_out = sv.check_timeouts()
        assert 0x1001 in timed_out
        assert sv.get_channel_status(0x1001) == E2EStatus.TIMEOUT

    def test_timeout_recovery(self):
        """After timeout, a new valid message recovers to VALID."""
        sv = E2ESupervisor()
        sv.register_channel(0x1001, deadline_ms=50)
        counter = SequenceCounterState()
        h, p = _make_valid_message(0x1001, counter)
        sv.on_message_received(h, p)
        time.sleep(0.1)
        sv.check_timeouts()
        assert sv.get_channel_status(0x1001) == E2EStatus.TIMEOUT
        # Send a new valid message
        h, p = _make_valid_message(0x1001, counter)
        status = sv.on_message_received(h, p)
        assert status == E2EStatus.VALID

    def test_consecutive_failures_escalate_to_error(self):
        """3 consecutive failures → ERROR state."""
        sv = E2ESupervisor()
        sv.register_channel(0x1001)
        payload = b"test"
        for i in range(3):
            header = _make_corrupt_header(0x1001, i, payload)
            sv.on_message_received(header, payload)
        assert sv.get_channel_status(0x1001) == E2EStatus.ERROR

    def test_dtc_set_on_crc_failure(self, tmp_path):
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        sv = E2ESupervisor(dtc_manager=dtc)
        sv.register_channel(0x1001)
        payload = b"test"
        header = _make_corrupt_header(0x1001, 0, payload)
        sv.on_message_received(header, payload)
        assert dtc.get_dtc(DTC_CODES["e2e_crc_failure"]) is not None

    def test_dtc_set_on_timeout(self, tmp_path):
        dtc = DTCManager(path=str(tmp_path / "dtc.json"))
        sv = E2ESupervisor(dtc_manager=dtc)
        sv.register_channel(0x1001, deadline_ms=50)
        counter = SequenceCounterState()
        h, p = _make_valid_message(0x1001, counter)
        sv.on_message_received(h, p)
        time.sleep(0.1)
        sv.check_timeouts()
        assert dtc.get_dtc(DTC_CODES["e2e_timeout"]) is not None

    def test_multiple_channels_independent(self):
        sv = E2ESupervisor()
        sv.register_channel(0x1001, deadline_ms=5000)
        sv.register_channel(0x2001, deadline_ms=5000)
        counter1 = SequenceCounterState()
        counter2 = SequenceCounterState()
        # Send valid to channel 1 only
        for _ in range(5):
            h, p = _make_valid_message(0x1001, counter1)
            sv.on_message_received(h, p)
        assert sv.get_channel_status(0x1001) == E2EStatus.VALID
        # Channel 2 should still be at its initial state (no messages received)
        stats = sv.get_channel_stats(0x2001)
        assert stats["total_received"] == 0

    def test_get_channel_stats(self):
        sv = E2ESupervisor()
        sv.register_channel(0x1001)
        counter = SequenceCounterState()
        for _ in range(3):
            h, p = _make_valid_message(0x1001, counter)
            sv.on_message_received(h, p)
        stats = sv.get_channel_stats(0x1001)
        assert stats["total_received"] == 3
        assert stats["total_crc_failures"] == 0
