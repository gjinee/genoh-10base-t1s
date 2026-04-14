"""E2E (End-to-End) Protection layer for communication integrity.

Implements AUTOSAR-style E2E protection with CRC-32, sequence counter,
and alive counter per functional_safety.md Section 2.

E2E Header (11 bytes, big-endian):
  data_id (16 bit) | seq_counter (16 bit) | alive_counter (8 bit)
  | length (16 bit) | crc32 (32 bit)
"""

from __future__ import annotations

import binascii
import struct
from dataclasses import dataclass, field

from src.common.safety_types import (
    DATA_ID_MAP,
    SEQUENCE_GAP_LIMITS,
    ASILLevel,
    E2EStatus,
)

# E2E header format: data_id(H) + seq(H) + alive(B) + length(H) + crc32(I)
E2E_HEADER_FORMAT = ">HHBHI"
E2E_HEADER_SIZE = struct.calcsize(E2E_HEADER_FORMAT)  # 11 bytes


@dataclass
class E2EHeader:
    """E2E protection header (11 bytes).

    Fields per Section 2.2.1:
      data_id:          16-bit message type ID (key expression hash)
      sequence_counter: 16-bit transmission sequence (0~65535, wrap-around)
      alive_counter:    8-bit periodic alive counter (0~255)
      length:           16-bit payload length in bytes
      crc32:            32-bit CRC over header fields + payload
    """
    data_id: int
    sequence_counter: int
    alive_counter: int
    length: int
    crc32: int

    def to_bytes(self) -> bytes:
        """Serialize header to 11 bytes (big-endian)."""
        return struct.pack(
            E2E_HEADER_FORMAT,
            self.data_id,
            self.sequence_counter,
            self.alive_counter,
            self.length,
            self.crc32,
        )

    @classmethod
    def from_bytes(cls, data: bytes) -> E2EHeader:
        """Deserialize header from bytes.

        Raises:
            ValueError: If data is shorter than 11 bytes.
        """
        if len(data) < E2E_HEADER_SIZE:
            raise ValueError(
                f"E2E header requires {E2E_HEADER_SIZE} bytes, got {len(data)}"
            )
        data_id, seq, alive, length, crc = struct.unpack(
            E2E_HEADER_FORMAT, data[:E2E_HEADER_SIZE]
        )
        return cls(
            data_id=data_id,
            sequence_counter=seq,
            alive_counter=alive,
            length=length,
            crc32=crc,
        )


def compute_e2e_crc(
    data_id: int,
    seq: int,
    alive: int,
    length: int,
    payload: bytes,
) -> int:
    """Compute CRC-32 over E2E header fields + payload.

    CRC polynomial: IEEE 802.3 (0x04C11DB7) via binascii.crc32.
    Input: data_id(2) + seq(2) + alive(1) + length(2) + payload(N)

    Per Section 2.2.3.
    """
    header_bytes = struct.pack(">HHBH", data_id, seq, alive, length)
    return binascii.crc32(header_bytes + payload) & 0xFFFFFFFF


@dataclass
class SequenceCounterState:
    """Per-data_id sequence counter state for transmission.

    Manages the 16-bit sequence counter and 8-bit alive counter
    that are incremented on each message transmission.
    """
    current_seq: int = 0
    alive_counter: int = 0

    def next(self) -> tuple[int, int]:
        """Get next (seq, alive) pair and increment counters.

        Returns:
            Tuple of (sequence_counter, alive_counter).
        """
        seq = self.current_seq
        alive = self.alive_counter
        self.current_seq = (self.current_seq + 1) % 65536
        self.alive_counter = (self.alive_counter + 1) % 256
        return seq, alive


class SequenceChecker:
    """Receiver-side sequence counter verification per Section 2.3.

    Tracks the last valid sequence number per data_id and checks
    incoming messages for repetition, gaps, or excessive loss.
    """

    def __init__(self, max_gap: int = 3):
        """
        Args:
            max_gap: Maximum allowed sequence gap before ERROR.
                     Depends on ASIL level (D=1, B=3, etc.).
        """
        self._max_gap = max_gap
        self._last_seq: int | None = None
        self._valid_count: int = 0
        self._init_count: int = 3  # Messages to receive before leaving INIT

    @property
    def last_seq(self) -> int | None:
        return self._last_seq

    def check(self, seq: int) -> str:
        """Check received sequence counter against expected.

        Args:
            seq: Received sequence counter value (0~65535).

        Returns:
            One of: "OK", "OK_SOME_LOST", "REPEATED", "ERROR", "INIT"
        """
        if self._last_seq is None:
            self._last_seq = seq
            self._valid_count = 1
            return "INIT"

        delta = (seq - self._last_seq) % 65536

        if delta == 0:
            return "REPEATED"

        if delta == 1:
            self._last_seq = seq
            self._valid_count += 1
            if self._valid_count < self._init_count:
                return "INIT"
            return "OK"

        if 2 <= delta <= self._max_gap:
            self._last_seq = seq
            return "OK_SOME_LOST"

        # delta > max_gap
        self._last_seq = seq
        return "ERROR"


def resolve_data_id(key_expr: str) -> int:
    """Map a Zenoh key expression to its E2E Data ID.

    Uses pattern matching: replaces zone/node_id segments with wildcards
    to find a matching entry in DATA_ID_MAP.

    Args:
        key_expr: Full Zenoh key expression, e.g.
                  "vehicle/front_left/1/sensor/temperature"

    Returns:
        16-bit Data ID integer.

    Raises:
        ValueError: If no matching Data ID is found.
    """
    # Direct match first
    if key_expr in DATA_ID_MAP:
        return DATA_ID_MAP[key_expr]

    # Try wildcard matching: vehicle/{zone}/{node_id}/{type}/{subtype}
    parts = key_expr.split("/")

    if len(parts) >= 5 and parts[0] == "vehicle":
        # vehicle/zone/node_id/sensor_or_actuator/type
        pattern = f"vehicle/*/{parts[3]}/{parts[4]}"
        if pattern in DATA_ID_MAP:
            return DATA_ID_MAP[pattern]

    if len(parts) >= 4 and parts[0] == "vehicle":
        # vehicle/zone/node_id/status
        pattern = f"vehicle/*/{parts[3]}"
        if pattern in DATA_ID_MAP:
            return DATA_ID_MAP[pattern]

    # vehicle/master/heartbeat or vehicle/master/diagnostics
    if len(parts) >= 3 and parts[0] == "vehicle":
        pattern = f"vehicle/{parts[1]}/{parts[2]}"
        if pattern in DATA_ID_MAP:
            return DATA_ID_MAP[pattern]

    raise ValueError(f"No Data ID mapping for key expression: {key_expr}")


def e2e_encode(
    data_id: int,
    payload: bytes,
    counter_state: SequenceCounterState,
) -> bytes:
    """Encode payload with E2E protection header.

    Prepends 11-byte E2E header (including CRC-32) to the payload.

    Args:
        data_id: 16-bit message type identifier.
        payload: Raw payload bytes (serialized JSON/CBOR).
        counter_state: Mutable counter state (incremented on each call).

    Returns:
        E2E-protected message: header (11 bytes) + payload.
    """
    seq, alive = counter_state.next()
    length = len(payload)
    crc = compute_e2e_crc(data_id, seq, alive, length, payload)
    header = E2EHeader(
        data_id=data_id,
        sequence_counter=seq,
        alive_counter=alive,
        length=length,
        crc32=crc,
    )
    return header.to_bytes() + payload


def e2e_decode(raw: bytes) -> tuple[E2EHeader, bytes]:
    """Decode an E2E-protected message into header and payload.

    Args:
        raw: Complete E2E message (header + payload).

    Returns:
        Tuple of (E2EHeader, payload_bytes).

    Raises:
        ValueError: If message is too short for E2E header.
    """
    header = E2EHeader.from_bytes(raw)
    payload = raw[E2E_HEADER_SIZE:]
    return header, payload


def e2e_verify(header: E2EHeader, payload: bytes) -> bool:
    """Verify E2E CRC-32 integrity.

    Recomputes CRC over header fields + payload and compares
    with the CRC stored in the header.

    Args:
        header: Decoded E2E header.
        payload: Payload bytes.

    Returns:
        True if CRC matches (message is intact).
    """
    expected_crc = compute_e2e_crc(
        header.data_id,
        header.sequence_counter,
        header.alive_counter,
        header.length,
        payload,
    )
    return header.crc32 == expected_crc
