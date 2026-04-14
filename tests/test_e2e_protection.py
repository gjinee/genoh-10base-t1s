"""Tests for Phase 2: E2E Protection Core.

Covers CRC-32 computation, E2E header encode/decode, sequence counter
management, and Data ID resolution. Test IDs correspond to FST-001~008
from functional_safety.md Section 9.1.
"""

import struct

import pytest

from src.common.e2e_protection import (
    E2E_HEADER_SIZE,
    E2EHeader,
    SequenceChecker,
    SequenceCounterState,
    compute_e2e_crc,
    e2e_decode,
    e2e_encode,
    e2e_verify,
    resolve_data_id,
)
from src.common.safety_types import DATA_ID_MAP


# ============================================================
# E2E CRC Tests
# ============================================================

class TestE2ECRC:
    """Test CRC-32 computation (FST-001, FST-002)."""

    def test_crc_valid_message(self):
        """FST-001: Known input produces a valid CRC-32."""
        payload = b'{"value":25.3,"unit":"celsius","ts":1713000000000}'
        crc = compute_e2e_crc(0x1001, 0, 0, len(payload), payload)
        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFFFFFF

    def test_crc_bit_flip_detected(self):
        """FST-002: 1-bit flip in payload produces different CRC."""
        payload = b'{"value":25.3}'
        crc_original = compute_e2e_crc(0x1001, 1, 0, len(payload), payload)

        # Flip one bit in payload
        corrupted = bytearray(payload)
        corrupted[5] ^= 0x01
        crc_corrupted = compute_e2e_crc(0x1001, 1, 0, len(corrupted), bytes(corrupted))

        assert crc_original != crc_corrupted

    def test_crc_deterministic(self):
        """Same input always produces the same CRC."""
        payload = b"hello"
        crc1 = compute_e2e_crc(0x1001, 42, 7, len(payload), payload)
        crc2 = compute_e2e_crc(0x1001, 42, 7, len(payload), payload)
        assert crc1 == crc2

    def test_crc_empty_payload(self):
        """CRC is valid on zero-length payload."""
        crc = compute_e2e_crc(0x1001, 0, 0, 0, b"")
        assert isinstance(crc, int)
        assert 0 <= crc <= 0xFFFFFFFF

    def test_crc_different_data_id(self):
        """Different data_id produces different CRC for same payload."""
        payload = b"test"
        crc1 = compute_e2e_crc(0x1001, 0, 0, len(payload), payload)
        crc2 = compute_e2e_crc(0x2001, 0, 0, len(payload), payload)
        assert crc1 != crc2


# ============================================================
# E2E Header Tests
# ============================================================

class TestE2EHeader:
    """Test E2E header encode/decode."""

    def test_header_size_11_bytes(self):
        """E2E header is exactly 11 bytes."""
        assert E2E_HEADER_SIZE == 11

    def test_encode_decode_roundtrip(self):
        """Encode then decode recovers all header fields."""
        header = E2EHeader(
            data_id=0x1003,
            sequence_counter=1234,
            alive_counter=56,
            length=100,
            crc32=0xDEADBEEF,
        )
        raw = header.to_bytes()
        assert len(raw) == 11

        restored = E2EHeader.from_bytes(raw)
        assert restored.data_id == 0x1003
        assert restored.sequence_counter == 1234
        assert restored.alive_counter == 56
        assert restored.length == 100
        assert restored.crc32 == 0xDEADBEEF

    def test_from_bytes_short_data_raises(self):
        """Less than 11 bytes raises ValueError."""
        with pytest.raises(ValueError, match="requires 11 bytes"):
            E2EHeader.from_bytes(b"\x00" * 10)

    def test_from_bytes_extra_data_ignored(self):
        """Extra bytes beyond 11 are ignored (payload follows)."""
        header = E2EHeader(0x1001, 0, 0, 5, 0x12345678)
        raw = header.to_bytes() + b"hello"
        restored = E2EHeader.from_bytes(raw)
        assert restored.data_id == 0x1001
        assert restored.crc32 == 0x12345678

    def test_data_id_mismatch_rejected(self):
        """FST-007: Wrong data_id fails CRC verification."""
        payload = b"test"
        data_id = 0x1001
        crc = compute_e2e_crc(data_id, 0, 0, len(payload), payload)

        # Verify with correct data_id
        header_ok = E2EHeader(data_id, 0, 0, len(payload), crc)
        assert e2e_verify(header_ok, payload)

        # Verify with wrong data_id
        header_bad = E2EHeader(0x2001, 0, 0, len(payload), crc)
        assert not e2e_verify(header_bad, payload)


# ============================================================
# Sequence Counter Tests
# ============================================================

class TestSequenceCounter:
    """Test sequence counter state management."""

    def test_counter_starts_at_zero(self):
        state = SequenceCounterState()
        seq, alive = state.next()
        assert seq == 0
        assert alive == 0

    def test_counter_increments(self):
        state = SequenceCounterState()
        for i in range(5):
            seq, alive = state.next()
            assert seq == i
            assert alive == i

    def test_seq_wraps_at_65535(self):
        state = SequenceCounterState(current_seq=65535, alive_counter=0)
        seq, _ = state.next()
        assert seq == 65535
        seq, _ = state.next()
        assert seq == 0  # Wrapped

    def test_alive_wraps_at_255(self):
        state = SequenceCounterState(current_seq=0, alive_counter=255)
        _, alive = state.next()
        assert alive == 255
        _, alive = state.next()
        assert alive == 0  # Wrapped


class TestSequenceChecker:
    """Test receiver-side sequence checking (FST-003~005, FST-008)."""

    def test_sequential_ok(self):
        """FST-003: Sequential reception is OK."""
        checker = SequenceChecker(max_gap=3)
        # First messages are INIT until init_count reached
        results = []
        for i in range(5):
            results.append(checker.check(i))
        assert results[0] == "INIT"
        assert results[1] == "INIT"
        assert results[2] == "OK"  # 3rd message = init_count reached
        assert results[3] == "OK"
        assert results[4] == "OK"

    def test_gap_exceeded_error(self):
        """FST-004: Gap > max_gap is ERROR."""
        checker = SequenceChecker(max_gap=3)
        checker.check(0)
        checker.check(1)
        checker.check(2)
        result = checker.check(10)  # Gap of 8 > 3
        assert result == "ERROR"

    def test_duplicate_detected(self):
        """FST-005: delta = 0 is REPEATED."""
        checker = SequenceChecker(max_gap=3)
        checker.check(0)
        checker.check(1)
        checker.check(2)
        result = checker.check(2)  # Same seq again
        assert result == "REPEATED"

    def test_wrap_around_65535_to_0(self):
        """FST-008: Wrap-around from 65535 to 0 is delta=1, OK."""
        checker = SequenceChecker(max_gap=3)
        checker.check(65533)
        checker.check(65534)
        checker.check(65535)
        result = checker.check(0)  # Wrap-around
        assert result == "OK"

    def test_gap_within_tolerance_ok_some_lost(self):
        """2 <= delta <= max_gap is OK_SOME_LOST (warning)."""
        checker = SequenceChecker(max_gap=3)
        checker.check(0)
        checker.check(1)
        checker.check(2)
        result = checker.check(5)  # Gap of 3 (delta=3, within max_gap)
        assert result == "OK_SOME_LOST"

    def test_asil_d_gap_1(self):
        """ASIL-D allows gap of only 1."""
        checker = SequenceChecker(max_gap=1)
        checker.check(0)
        checker.check(1)
        checker.check(2)
        result = checker.check(4)  # Gap of 2 > 1
        assert result == "ERROR"


# ============================================================
# Data ID Mapping Tests
# ============================================================

class TestDataIDMapping:
    """Test resolve_data_id key expression to Data ID mapping."""

    def test_resolve_sensor_keys(self):
        """All 5 sensor types resolve correctly."""
        for sensor in ["temperature", "pressure", "proximity", "light", "battery"]:
            data_id = resolve_data_id(f"vehicle/front_left/1/sensor/{sensor}")
            expected = DATA_ID_MAP[f"vehicle/*/sensor/{sensor}"]
            assert data_id == expected

    def test_resolve_actuator_keys(self):
        """All 5 actuator types resolve correctly."""
        for actuator in ["led", "motor", "relay", "buzzer", "lock"]:
            data_id = resolve_data_id(f"vehicle/rear_right/3/actuator/{actuator}")
            expected = DATA_ID_MAP[f"vehicle/*/actuator/{actuator}"]
            assert data_id == expected

    def test_resolve_status_key(self):
        data_id = resolve_data_id("vehicle/front_left/1/status")
        assert data_id == 0x3000

    def test_resolve_master_heartbeat(self):
        data_id = resolve_data_id("vehicle/master/heartbeat")
        assert data_id == 0x3F01

    def test_resolve_unknown_key_raises(self):
        with pytest.raises(ValueError, match="No Data ID mapping"):
            resolve_data_id("vehicle/front/1/unknown/thing")


# ============================================================
# E2E Encode/Decode Integration Tests
# ============================================================

class TestE2EEncodeDecode:
    """Test full E2E encode → decode → verify cycle."""

    def test_encode_decode_verify(self):
        """Full roundtrip: encode, decode, verify CRC."""
        counter = SequenceCounterState()
        payload = b'{"value":25.3,"unit":"celsius"}'

        encoded = e2e_encode(0x1001, payload, counter)
        assert len(encoded) == E2E_HEADER_SIZE + len(payload)

        header, decoded_payload = e2e_decode(encoded)
        assert header.data_id == 0x1001
        assert header.sequence_counter == 0
        assert header.length == len(payload)
        assert decoded_payload == payload
        assert e2e_verify(header, decoded_payload)

    def test_corrupted_payload_fails_verify(self):
        """Corrupted payload fails CRC verification."""
        counter = SequenceCounterState()
        payload = b'{"value":25.3}'

        encoded = e2e_encode(0x1001, payload, counter)
        corrupted = bytearray(encoded)
        corrupted[-1] ^= 0xFF  # Flip last byte of payload
        header, bad_payload = e2e_decode(bytes(corrupted))
        assert not e2e_verify(header, bad_payload)

    def test_sequential_encoding_increments_seq(self):
        """Multiple encodes increment sequence counter."""
        counter = SequenceCounterState()
        for i in range(3):
            encoded = e2e_encode(0x1001, b"test", counter)
            header, _ = e2e_decode(encoded)
            assert header.sequence_counter == i
