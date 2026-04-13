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
