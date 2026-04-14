"""Payload serialization/deserialization for Zenoh messages.

Supports JSON and CBOR encoding per PRD Section 5.2:
- Slave (MCU) ↔ Master: CBOR (bandwidth optimization on 10Mbps bus)
- Debugging/CLI: JSON (human-readable)
- Scenario files: YAML/JSON

The master auto-detects encoding via Zenoh Content-Type header
(application/json or application/cbor).
"""

from __future__ import annotations

import json
from typing import Any

import cbor2

from src.common.e2e_protection import (
    E2EHeader,
    SequenceCounterState,
    e2e_decode,
    e2e_encode,
    e2e_verify,
    resolve_data_id,
)


# --- Encoding identifiers ---
ENCODING_JSON = "application/json"
ENCODING_CBOR = "application/cbor"


def encode_json(data: dict | list) -> bytes:
    """Encode payload as JSON bytes."""
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def decode_json(raw: bytes | str) -> Any:
    """Decode JSON payload."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def encode_cbor(data: dict | list) -> bytes:
    """Encode payload as CBOR bytes."""
    return cbor2.dumps(data)


def decode_cbor(raw: bytes) -> Any:
    """Decode CBOR payload."""
    return cbor2.loads(raw)


def encode(data: dict | list, encoding: str = ENCODING_JSON) -> bytes:
    """Encode payload with the specified encoding.

    Args:
        data: Python dict/list to serialize.
        encoding: "application/json" or "application/cbor".
    """
    if encoding == ENCODING_CBOR:
        return encode_cbor(data)
    return encode_json(data)


def decode(raw: bytes | str, encoding: str | None = None) -> Any:
    """Decode payload, auto-detecting encoding if not specified.

    Args:
        raw: Raw bytes or string from Zenoh sample.
        encoding: Content-Type hint. If None, tries JSON first, then CBOR.
    """
    if encoding == ENCODING_CBOR:
        return decode_cbor(raw if isinstance(raw, bytes) else raw.encode("utf-8"))
    if encoding == ENCODING_JSON:
        return decode_json(raw)

    # Auto-detect: try JSON first (starts with { or [), then CBOR
    if isinstance(raw, str):
        return decode_json(raw)

    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
            if text.startswith(("{", "[")):
                return decode_json(text)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return decode_cbor(raw)

    raise ValueError(f"Cannot decode payload of type {type(raw)}")


# --- E2E Protection wrappers ---

def encode_e2e(
    data: dict | list,
    key_expr: str,
    counter_state: SequenceCounterState,
    encoding: str = ENCODING_JSON,
) -> bytes:
    """Encode payload with E2E protection header.

    Serializes data with the specified encoding, then wraps with
    an 11-byte E2E header including CRC-32.

    Args:
        data: Python dict/list to serialize.
        key_expr: Zenoh key expression (for Data ID resolution).
        counter_state: Mutable sequence counter state.
        encoding: Payload encoding type.

    Returns:
        E2E-protected message bytes (header + payload).
    """
    payload = encode(data, encoding)
    data_id = resolve_data_id(key_expr)
    return e2e_encode(data_id, payload, counter_state)


def decode_e2e(
    raw: bytes,
    encoding: str | None = None,
) -> tuple[dict | list, E2EHeader, bool]:
    """Decode an E2E-protected message.

    Splits the E2E header from the payload, verifies CRC,
    and decodes the inner payload.

    Args:
        raw: Complete E2E message (header + payload).
        encoding: Payload encoding hint.

    Returns:
        Tuple of (decoded_data, E2EHeader, crc_valid).
    """
    header, payload = e2e_decode(raw)
    crc_valid = e2e_verify(header, payload)
    data = decode(payload, encoding)
    return data, header, crc_valid


# --- SecOC wrappers (requires key) ---

def encode_secoc(
    data: dict | list,
    key_expr: str,
    counter_state: SequenceCounterState,
    secoc_key: bytes,
    encoding: str = ENCODING_JSON,
) -> bytes:
    """Encode payload with E2E + SecOC protection.

    Applies E2E protection first, then wraps with SecOC
    (Freshness + HMAC-SHA256).

    Args:
        data: Python dict/list to serialize.
        key_expr: Zenoh key expression.
        counter_state: Mutable sequence counter state.
        secoc_key: 256-bit HMAC key for SecOC.
        encoding: Payload encoding type.

    Returns:
        Fully protected message bytes (E2E + SecOC).
    """
    from src.master.secoc import FreshnessCounter, secoc_encode as _secoc_encode

    e2e_msg = encode_e2e(data, key_expr, counter_state, encoding)
    fc = FreshnessCounter()
    return _secoc_encode(secoc_key, e2e_msg, fc)


def decode_secoc(
    raw: bytes,
    secoc_key: bytes,
    encoding: str | None = None,
) -> tuple[dict | list | None, E2EHeader | None, bool, bool]:
    """Decode a SecOC + E2E protected message.

    Verifies SecOC (MAC + Freshness) first, then E2E (CRC + Seq).

    Args:
        raw: Complete protected message.
        secoc_key: 256-bit HMAC key.
        encoding: Payload encoding hint.

    Returns:
        Tuple of (decoded_data, E2EHeader, crc_valid, mac_valid).
        If MAC fails, decoded_data may be None.
    """
    from src.master.secoc import secoc_decode as _secoc_decode

    e2e_msg, fv, mac_valid = _secoc_decode(secoc_key, raw, window_ms=10000)
    if not mac_valid or not e2e_msg:
        return None, None, False, False

    data, header, crc_valid = decode_e2e(e2e_msg, encoding)
    return data, header, crc_valid, mac_valid
