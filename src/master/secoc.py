"""SecOC (Secure Onboard Communication) — HMAC message authentication.

Implements AUTOSAR SecOC-style message authentication with HMAC-SHA256
(truncated to 128 bits) and Freshness Value for replay prevention.
See cybersecurity.md Section 3.2.
"""

from __future__ import annotations

import hashlib
import hmac
import struct
import time
from dataclasses import dataclass

from src.common.security_types import FRESHNESS_WINDOW_MS

# SecOC overhead: Freshness (8 bytes) + MAC (16 bytes) = 24 bytes
FRESHNESS_SIZE = 8
MAC_SIZE = 16  # HMAC-SHA256 truncated to 128 bits
SECOC_OVERHEAD = FRESHNESS_SIZE + MAC_SIZE


@dataclass
class FreshnessValue:
    """Freshness value for replay prevention (Section 3.3.1).

    Structure (64 bits):
      timestamp_ms (48 bits): milliseconds since epoch
      counter (16 bits): per-timestamp sequence number
    """
    timestamp_ms: int
    counter: int = 0

    def to_bytes(self) -> bytes:
        """Serialize to 8 bytes (big-endian)."""
        # Pack as: 48-bit timestamp (6 bytes) + 16-bit counter (2 bytes)
        ts_bytes = self.timestamp_ms.to_bytes(6, byteorder="big")
        cnt_bytes = self.counter.to_bytes(2, byteorder="big")
        return ts_bytes + cnt_bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> FreshnessValue:
        """Deserialize from 8 bytes."""
        if len(data) < FRESHNESS_SIZE:
            raise ValueError(f"Freshness value requires {FRESHNESS_SIZE} bytes")
        ts = int.from_bytes(data[:6], byteorder="big")
        cnt = int.from_bytes(data[6:8], byteorder="big")
        return cls(timestamp_ms=ts, counter=cnt)

    def __le__(self, other: FreshnessValue) -> bool:
        if self.timestamp_ms < other.timestamp_ms:
            return True
        if self.timestamp_ms == other.timestamp_ms:
            return self.counter <= other.counter
        return False

    def __gt__(self, other: FreshnessValue) -> bool:
        return not self.__le__(other)


class FreshnessCounter:
    """Manages freshness value generation for transmission."""

    def __init__(self):
        self._last_ts_ms: int = 0
        self._counter: int = 0

    def next(self) -> FreshnessValue:
        """Generate next freshness value."""
        now_ms = int(time.time() * 1000)
        if now_ms == self._last_ts_ms:
            self._counter = (self._counter + 1) % 65536
        else:
            self._last_ts_ms = now_ms
            self._counter = 0
        return FreshnessValue(timestamp_ms=now_ms, counter=self._counter)


def compute_mac(
    key: bytes,
    data: bytes,
    freshness: FreshnessValue,
) -> bytes:
    """Compute HMAC-SHA256 truncated to 128 bits (16 bytes).

    MAC input: data + freshness_value_bytes

    Args:
        key: 256-bit HMAC key.
        data: E2E header + payload bytes.
        freshness: Freshness value for this message.

    Returns:
        16-byte truncated MAC.
    """
    mac_input = data + freshness.to_bytes()
    full_mac = hmac.new(key, mac_input, hashlib.sha256).digest()
    return full_mac[:MAC_SIZE]


def secoc_encode(
    key: bytes,
    data: bytes,
    freshness_counter: FreshnessCounter,
) -> bytes:
    """Encode data with SecOC protection (Freshness + MAC).

    Output format: data + freshness(8B) + mac(16B)

    Args:
        key: 256-bit HMAC key.
        data: Input bytes (typically E2E-protected message).
        freshness_counter: Counter for freshness generation.

    Returns:
        SecOC-protected message (data + 24 bytes overhead).
    """
    fv = freshness_counter.next()
    mac = compute_mac(key, data, fv)
    return data + fv.to_bytes() + mac


def secoc_decode(
    key: bytes,
    raw: bytes,
    last_freshness: FreshnessValue | None = None,
    window_ms: int = FRESHNESS_WINDOW_MS,
) -> tuple[bytes, FreshnessValue, bool]:
    """Decode and verify a SecOC-protected message.

    Args:
        key: 256-bit HMAC key.
        raw: Complete SecOC message (data + freshness + mac).
        last_freshness: Last valid freshness for replay detection.
        window_ms: Maximum allowed timestamp deviation from now.

    Returns:
        Tuple of (data, freshness_value, is_valid).
        is_valid is True if both MAC and freshness checks pass.
    """
    if len(raw) < SECOC_OVERHEAD:
        return b"", FreshnessValue(0, 0), False

    # Split: data | freshness(8) | mac(16)
    mac_received = raw[-MAC_SIZE:]
    fv_bytes = raw[-(MAC_SIZE + FRESHNESS_SIZE):-MAC_SIZE]
    data = raw[:-(MAC_SIZE + FRESHNESS_SIZE)]

    fv = FreshnessValue.from_bytes(fv_bytes)

    # Verify MAC
    mac_expected = compute_mac(key, data, fv)
    mac_valid = hmac.compare_digest(mac_received, mac_expected)

    if not mac_valid:
        return data, fv, False

    # Verify freshness (replay protection)
    # Check 1: Not a replay of past message
    if last_freshness is not None:
        if fv <= last_freshness:
            return data, fv, False

    # Check 2: Timestamp within acceptable window
    now_ms = int(time.time() * 1000)
    if abs(fv.timestamp_ms - now_ms) > window_ms:
        return data, fv, False

    return data, fv, True
