"""Zenoh Key Expression definitions for the 10BASE-T1S automotive network.

Key expression hierarchy (PRD Section 5.1):
  vehicle/{zone}/{node_id}/sensor/{type}
  vehicle/{zone}/{node_id}/actuator/{type}
  vehicle/{zone}/{node_id}/status
  vehicle/{zone}/{node_id}/alive
  vehicle/{zone}/{node_id}/config
  vehicle/{zone}/summary
  vehicle/master/heartbeat|command|diagnostics
"""

from __future__ import annotations

# --- Zone identifiers ---
ZONES = ("front_left", "front_right", "rear_left", "rear_right", "front", "rear")

# --- Sensor types ---
SENSOR_TYPES = ("temperature", "pressure", "proximity", "light", "battery")

# --- Actuator types ---
ACTUATOR_TYPES = ("led", "motor", "relay", "buzzer", "lock")


# --- Key expression builders ---

def sensor_key(zone: str, node_id: int | str, sensor_type: str) -> str:
    """Build a sensor data key expression.

    Example: vehicle/front_left/1/sensor/temperature
    """
    return f"vehicle/{zone}/{node_id}/sensor/{sensor_type}"


def actuator_key(zone: str, node_id: int | str, actuator_type: str) -> str:
    """Build an actuator command key expression.

    Example: vehicle/front_left/2/actuator/lock
    """
    return f"vehicle/{zone}/{node_id}/actuator/{actuator_type}"


def status_key(zone: str, node_id: int | str) -> str:
    """Build a node status query key expression.

    Example: vehicle/front_left/1/status
    """
    return f"vehicle/{zone}/{node_id}/status"


def alive_key(zone: str, node_id: int | str) -> str:
    """Build a liveliness token key expression.

    Example: vehicle/front_left/1/alive
    """
    return f"vehicle/{zone}/{node_id}/alive"


def config_key(zone: str, node_id: int | str) -> str:
    """Build a node config key expression."""
    return f"vehicle/{zone}/{node_id}/config"


def zone_summary_key(zone: str) -> str:
    """Build a zone summary key expression."""
    return f"vehicle/{zone}/summary"


# --- Master key expressions ---

MASTER_HEARTBEAT = "vehicle/master/heartbeat"
MASTER_COMMAND = "vehicle/master/command"
MASTER_DIAGNOSTICS = "vehicle/master/diagnostics"


# --- Wildcard patterns for subscriptions ---

def all_sensors_pattern(zone: str = "*", node_id: str = "*", sensor_type: str = "*") -> str:
    """Wildcard pattern for sensor subscriptions.

    Examples:
      all_sensors_pattern()                          → vehicle/*/*/sensor/*
      all_sensors_pattern(zone="front_left")         → vehicle/front_left/*/sensor/*
      all_sensors_pattern(sensor_type="temperature") → vehicle/*/*/sensor/temperature
    """
    return f"vehicle/{zone}/{node_id}/sensor/{sensor_type}"


def all_actuators_pattern(zone: str = "*", node_id: str = "*") -> str:
    """Wildcard pattern for actuator subscriptions."""
    return f"vehicle/{zone}/{node_id}/actuator/*"


def all_status_pattern(zone: str = "*") -> str:
    """Wildcard pattern for status queries."""
    return f"vehicle/{zone}/*/status"


def all_alive_pattern(zone: str = "*") -> str:
    """Wildcard pattern for liveliness subscriptions."""
    return f"vehicle/{zone}/*/alive"


# --- Key expression parsing ---

def parse_key_expr(key_expr: str) -> dict[str, str] | None:
    """Parse a vehicle key expression into components.

    Returns dict with keys: zone, node_id, category, type
    or None if the key expression doesn't match the expected pattern.

    Example:
      parse_key_expr("vehicle/front_left/1/sensor/temperature")
      → {"zone": "front_left", "node_id": "1", "category": "sensor", "type": "temperature"}
    """
    parts = key_expr.split("/")
    if len(parts) < 2 or parts[0] != "vehicle":
        return None

    result: dict[str, str] = {}

    if len(parts) == 5:
        # vehicle/{zone}/{node_id}/{category}/{type}
        result["zone"] = parts[1]
        result["node_id"] = parts[2]
        result["category"] = parts[3]
        result["type"] = parts[4]
    elif len(parts) == 4:
        # vehicle/{zone}/{node_id}/{status|alive|config}
        result["zone"] = parts[1]
        result["node_id"] = parts[2]
        result["category"] = parts[3]
    elif len(parts) == 3:
        # vehicle/{zone}/summary or vehicle/master/{type}
        result["zone"] = parts[1]
        result["category"] = parts[2]
    else:
        return None

    return result
