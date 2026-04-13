"""Tests for payload serialization (PRD Section 5.2)."""

import json

from src.common.payloads import (
    ENCODING_CBOR,
    ENCODING_JSON,
    decode,
    decode_cbor,
    decode_json,
    encode,
    encode_cbor,
    encode_json,
)


class TestJSONCodec:
    def test_encode_decode(self):
        data = {"value": 25.3, "unit": "celsius", "ts": 1713000000000}
        encoded = encode_json(data)
        assert isinstance(encoded, bytes)
        decoded = decode_json(encoded)
        assert decoded["value"] == 25.3
        assert decoded["unit"] == "celsius"

    def test_encode_compact(self):
        """JSON should use compact separators for bandwidth efficiency."""
        encoded = encode_json({"a": 1})
        assert b" " not in encoded  # no extra whitespace


class TestCBORCodec:
    def test_encode_decode(self):
        data = {"value": 101.3, "unit": "kpa", "ts": 1713000000000}
        encoded = encode_cbor(data)
        assert isinstance(encoded, bytes)
        decoded = decode_cbor(encoded)
        assert decoded["value"] == 101.3

    def test_cbor_smaller_than_json(self):
        """CBOR should be more compact than JSON (PRD: bandwidth optimization)."""
        data = {"value": 25.3, "unit": "celsius", "ts": 1713000000000}
        json_bytes = encode_json(data)
        cbor_bytes = encode_cbor(data)
        assert len(cbor_bytes) < len(json_bytes)


class TestUnifiedCodec:
    def test_encode_json(self):
        data = {"test": True}
        result = encode(data, ENCODING_JSON)
        assert json.loads(result) == {"test": True}

    def test_encode_cbor(self):
        data = {"test": True}
        result = encode(data, ENCODING_CBOR)
        decoded = decode_cbor(result)
        assert decoded["test"] is True

    def test_auto_detect_json_bytes(self):
        data = {"value": 42}
        raw = json.dumps(data).encode("utf-8")
        result = decode(raw)
        assert result["value"] == 42

    def test_auto_detect_json_string(self):
        result = decode('{"value": 42}')
        assert result["value"] == 42

    def test_auto_detect_cbor(self):
        data = {"value": 42}
        raw = encode_cbor(data)
        result = decode(raw)
        assert result["value"] == 42

    def test_explicit_encoding(self):
        data = {"x": 1}
        json_bytes = encode(data, ENCODING_JSON)
        assert decode(json_bytes, ENCODING_JSON) == {"x": 1}

        cbor_bytes = encode(data, ENCODING_CBOR)
        assert decode(cbor_bytes, ENCODING_CBOR) == {"x": 1}


class TestSensorPayloadFormat:
    """Test the actual payload format from PRD Section 5.2."""

    def test_sensor_payload(self):
        """Slave → Master sensor data format."""
        payload = {"value": 25.3, "unit": "celsius", "ts": 1713000000000}
        encoded = encode(payload, ENCODING_JSON)
        decoded = decode(encoded, ENCODING_JSON)
        assert decoded == payload

    def test_actuator_payload(self):
        """Master → Slave actuator command format."""
        payload = {
            "action": "set",
            "params": {"state": "on", "brightness": 80, "color": "white"},
            "ts": 1713000000100,
        }
        for enc in [ENCODING_JSON, ENCODING_CBOR]:
            encoded = encode(payload, enc)
            decoded = decode(encoded, enc)
            assert decoded["action"] == "set"
            assert decoded["params"]["brightness"] == 80
