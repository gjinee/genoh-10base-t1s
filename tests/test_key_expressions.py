"""Tests for Zenoh key expression builder and parser (PRD Section 5.1)."""

from src.common.key_expressions import (
    actuator_key,
    alive_key,
    all_alive_pattern,
    all_sensors_pattern,
    config_key,
    parse_key_expr,
    sensor_key,
    status_key,
    zone_summary_key,
    MASTER_HEARTBEAT,
    MASTER_DIAGNOSTICS,
)


class TestKeyBuilders:
    def test_sensor_key(self):
        assert sensor_key("front_left", 1, "temperature") == "vehicle/front_left/1/sensor/temperature"

    def test_actuator_key(self):
        assert actuator_key("rear_right", 2, "led") == "vehicle/rear_right/2/actuator/led"

    def test_status_key(self):
        assert status_key("front", "3") == "vehicle/front/3/status"

    def test_alive_key(self):
        assert alive_key("rear_left", 4) == "vehicle/rear_left/4/alive"

    def test_config_key(self):
        assert config_key("front_right", 5) == "vehicle/front_right/5/config"

    def test_zone_summary_key(self):
        assert zone_summary_key("front") == "vehicle/front/summary"

    def test_master_constants(self):
        assert MASTER_HEARTBEAT == "vehicle/master/heartbeat"
        assert MASTER_DIAGNOSTICS == "vehicle/master/diagnostics"


class TestWildcardPatterns:
    def test_all_sensors_default(self):
        assert all_sensors_pattern() == "vehicle/*/*/sensor/*"

    def test_all_sensors_filtered_zone(self):
        assert all_sensors_pattern(zone="front_left") == "vehicle/front_left/*/sensor/*"

    def test_all_sensors_filtered_type(self):
        assert all_sensors_pattern(sensor_type="temperature") == "vehicle/*/*/sensor/temperature"

    def test_all_alive_default(self):
        assert all_alive_pattern() == "vehicle/*/*/alive"


class TestParseKeyExpr:
    def test_parse_sensor(self):
        result = parse_key_expr("vehicle/front_left/1/sensor/temperature")
        assert result == {
            "zone": "front_left",
            "node_id": "1",
            "category": "sensor",
            "type": "temperature",
        }

    def test_parse_actuator(self):
        result = parse_key_expr("vehicle/rear_right/2/actuator/lock")
        assert result == {
            "zone": "rear_right",
            "node_id": "2",
            "category": "actuator",
            "type": "lock",
        }

    def test_parse_status(self):
        result = parse_key_expr("vehicle/front/3/status")
        assert result == {
            "zone": "front",
            "node_id": "3",
            "category": "status",
        }

    def test_parse_alive(self):
        result = parse_key_expr("vehicle/front_left/1/alive")
        assert result == {
            "zone": "front_left",
            "node_id": "1",
            "category": "alive",
        }

    def test_parse_zone_summary(self):
        result = parse_key_expr("vehicle/front/summary")
        assert result == {"zone": "front", "category": "summary"}

    def test_parse_invalid(self):
        assert parse_key_expr("invalid/key") is None
        assert parse_key_expr("") is None

    def test_parse_non_vehicle(self):
        assert parse_key_expr("other/front/1/sensor/temp") is None
