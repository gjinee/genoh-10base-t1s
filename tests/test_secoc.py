"""Tests for SecOC (Secure Onboard Communication) — HMAC + Freshness.

Test IDs: CST-004~006 from cybersecurity.md Section 10.1.
"""

import os
import time

import pytest

from src.master.secoc import (
    SECOC_OVERHEAD,
    MAC_SIZE,
    FRESHNESS_SIZE,
    FreshnessCounter,
    FreshnessValue,
    compute_mac,
    secoc_decode,
    secoc_encode,
)


class TestFreshnessValue:
    """Test FreshnessValue encode/decode."""

    def test_encode_decode_roundtrip(self):
        fv = FreshnessValue(timestamp_ms=1713000000000, counter=42)
        raw = fv.to_bytes()
        assert len(raw) == FRESHNESS_SIZE
        restored = FreshnessValue.from_bytes(raw)
        assert restored.timestamp_ms == 1713000000000
        assert restored.counter == 42

    def test_comparison_operators(self):
        fv1 = FreshnessValue(1000, 0)
        fv2 = FreshnessValue(1000, 1)
        fv3 = FreshnessValue(1001, 0)
        assert fv1 <= fv2
        assert fv2 <= fv3
        assert fv3 > fv1


class TestSecOCMAC:
    """Test HMAC computation and verification."""

    def test_mac_valid_verification(self):
        """CST-004: Valid MAC is accepted."""
        key = os.urandom(32)
        data = b"test_payload"
        fv = FreshnessValue(int(time.time() * 1000), 0)
        mac = compute_mac(key, data, fv)
        assert len(mac) == MAC_SIZE
        # Recompute should match
        mac2 = compute_mac(key, data, fv)
        assert mac == mac2

    def test_mac_tampered_rejected(self):
        """CST-005: Altered MAC is rejected."""
        key = os.urandom(32)
        data = b"test_payload"
        fv = FreshnessValue(int(time.time() * 1000), 0)
        mac = compute_mac(key, data, fv)
        # Tamper with data
        tampered = b"tampered_data"
        mac_tampered = compute_mac(key, tampered, fv)
        assert mac != mac_tampered

    def test_different_keys_different_macs(self):
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        data = b"same_data"
        fv = FreshnessValue(int(time.time() * 1000), 0)
        mac1 = compute_mac(key1, data, fv)
        mac2 = compute_mac(key2, data, fv)
        assert mac1 != mac2

    def test_mac_truncation_to_128_bits(self):
        """Output is exactly 16 bytes (128 bits)."""
        key = os.urandom(32)
        mac = compute_mac(key, b"data", FreshnessValue(0, 0))
        assert len(mac) == 16


class TestSecOCEncodeDecode:
    """Test full SecOC encode/decode cycle."""

    def test_secoc_encode_decode_roundtrip(self):
        key = os.urandom(32)
        data = b'{"value":25.3,"unit":"celsius"}'
        fc = FreshnessCounter()
        encoded = secoc_encode(key, data, fc)
        assert len(encoded) == len(data) + SECOC_OVERHEAD

        decoded_data, fv, valid = secoc_decode(key, encoded, window_ms=10000)
        assert valid is True
        assert decoded_data == data

    def test_secoc_overhead_24_bytes(self):
        assert SECOC_OVERHEAD == 24

    def test_replay_rejected(self):
        """CST-006: Past freshness value is rejected."""
        key = os.urandom(32)
        data = b"command"
        fc = FreshnessCounter()
        encoded1 = secoc_encode(key, data, fc)
        _, fv1, valid1 = secoc_decode(key, encoded1, window_ms=10000)
        assert valid1 is True

        # Decode the same message again with last_freshness set
        _, _, valid2 = secoc_decode(key, encoded1, last_freshness=fv1, window_ms=10000)
        assert valid2 is False  # Replay detected

    def test_wrong_key_rejected(self):
        key1 = os.urandom(32)
        key2 = os.urandom(32)
        data = b"secret"
        fc = FreshnessCounter()
        encoded = secoc_encode(key1, data, fc)
        _, _, valid = secoc_decode(key2, encoded, window_ms=10000)
        assert valid is False

    def test_freshness_window_exceeded(self):
        """Timestamp too far from current time is rejected."""
        key = os.urandom(32)
        data = b"data"
        # Manually create a message with old timestamp
        fv_old = FreshnessValue(timestamp_ms=1000, counter=0)
        mac = compute_mac(key, data, fv_old)
        raw = data + fv_old.to_bytes() + mac
        _, _, valid = secoc_decode(key, raw, window_ms=5000)
        assert valid is False

    def test_short_message_returns_invalid(self):
        key = os.urandom(32)
        _, _, valid = secoc_decode(key, b"short")
        assert valid is False
