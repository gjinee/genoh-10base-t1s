"""Scenario-based simulation engine.

Implements PRD FR-008: Scenario-based simulation.
Loads YAML scenario files and executes step sequences on the Zenoh network.

Supported scenario actions (PRD Section 10):
  - publish: Put data to a key expression
  - subscribe: Subscribe to a key expression
  - wait_sensor: Wait until a sensor condition is met
  - query: Query a node's status
  - log: Log a message
  - delay: Wait for a specified time

Conditions use simple comparison operators only:
  <, >, <=, >=, ==, != (PRD Section 4.3)
"""

from __future__ import annotations

import asyncio
import logging
import operator
import time
from pathlib import Path
from typing import Any

import yaml

from src.common import key_expressions as ke
from src.common import payloads
from src.common.models import ActuatorCommand, SensorData
from src.master.zenoh_master import ZenohMaster

logger = logging.getLogger(__name__)

# Supported comparison operators (PRD: 단순 비교 연산자만 지원)
OPERATORS = {
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


class Scenario:
    """Parsed scenario from a YAML file."""

    def __init__(self, data: dict) -> None:
        self.name: str = data.get("name", "unnamed")
        self.description: str = data.get("description", "")
        self.zone: str = data.get("zone", "all")
        self.interval_ms: int = data.get("interval_ms", 1000)
        self.nodes: list[dict] = data.get("nodes", [])
        self.sequence: list[dict] = data.get("sequence", [])
        self.subscribe_patterns: list[dict] = data.get("subscribe", [])
        self.aggregation: dict | None = data.get("aggregation")

    @classmethod
    def from_yaml(cls, path: str | Path) -> Scenario:
        """Load a scenario from a YAML file."""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(data)


class ScenarioRunner:
    """Executes simulation scenarios on the Zenoh network.

    Parses YAML scenarios and runs the step sequences, interacting with
    the ZenohMaster for pub/sub/query operations.
    """

    def __init__(self, zenoh_master: ZenohMaster) -> None:
        self._zenoh = zenoh_master
        self._latest_values: dict[str, float] = {}
        self._running = False

    async def run(self, scenario: Scenario) -> None:
        """Execute a scenario's step sequence."""
        logger.info("=== Scenario: %s ===", scenario.name)
        logger.info("Description: %s", scenario.description)
        logger.info("Zone: %s, Nodes: %d, Steps: %d",
                     scenario.zone, len(scenario.nodes), len(scenario.sequence))

        self._running = True

        # Set up subscriptions to track sensor values
        self._setup_value_tracking(scenario)

        # Execute each step
        for step_def in scenario.sequence:
            if not self._running:
                logger.info("Scenario stopped")
                break

            step_num = step_def.get("step", "?")
            action = step_def.get("action", "")
            description = step_def.get("description", "")

            logger.info("[Step %s] %s — %s", step_num, action, description)

            try:
                await self._execute_step(step_def)
            except Exception as e:
                logger.error("[Step %s] Failed: %s", step_num, e)

        self._running = False
        logger.info("=== Scenario complete: %s ===", scenario.name)

    def stop(self) -> None:
        """Stop the running scenario."""
        self._running = False

    async def _execute_step(self, step: dict) -> None:
        """Dispatch a single scenario step to its handler."""
        action = step.get("action", "")

        # Handle delay_ms before the action
        delay_ms = step.get("delay_ms", 0)
        if delay_ms > 0:
            logger.info("  Waiting %d ms...", delay_ms)
            await asyncio.sleep(delay_ms / 1000.0)

        if action == "publish":
            await self._action_publish(step)
        elif action == "subscribe":
            await self._action_subscribe(step)
        elif action == "wait_sensor":
            await self._action_wait_sensor(step)
        elif action == "query":
            await self._action_query(step)
        elif action == "log":
            self._action_log(step)
        else:
            logger.warning("  Unknown action: %s", action)

    async def _action_publish(self, step: dict) -> None:
        """Publish data to a key expression."""
        key = step["key"]
        payload = step.get("payload", {})

        # Parse key to determine if it's an actuator command
        parsed = ke.parse_key_expr(key)
        if parsed and parsed.get("category") == "actuator":
            cmd = ActuatorCommand(
                action=payload.get("action", "set"),
                params=payload.get("params", payload),
            )
            self._zenoh.publish_actuator(
                parsed["zone"], parsed["node_id"], parsed["type"], cmd,
            )
        else:
            self._zenoh.put(key, payload)

        logger.info("  Published → %s: %s", key, payload)

    async def _action_subscribe(self, step: dict) -> None:
        """Subscribe to a key expression."""
        key = step["key"]
        self._zenoh.subscribe_sensors(callback=self._on_sensor_value)
        logger.info("  Subscribed → %s", key)

    async def _action_wait_sensor(self, step: dict) -> None:
        """Wait until a sensor condition is met.

        Condition format:
          condition:
            key: vehicle/front_left/1/sensor/proximity
            operator: "<"
            threshold: 30
        """
        condition = step.get("condition", {})
        key = condition.get("key", "")
        op_str = condition.get("operator", "==")
        threshold = condition.get("threshold", 0)

        op_func = OPERATORS.get(op_str)
        if not op_func:
            logger.error("  Unknown operator: %s", op_str)
            return

        logger.info("  Waiting for %s %s %s ...", key, op_str, threshold)
        timeout = 30.0  # Max wait time
        start = time.time()

        while self._running and (time.time() - start) < timeout:
            value = self._latest_values.get(key)
            if value is not None and op_func(value, threshold):
                logger.info("  Condition met: %s=%s %s %s", key, value, op_str, threshold)
                return
            await asyncio.sleep(0.1)

        logger.warning("  Condition timeout after %.1fs", time.time() - start)

    async def _action_query(self, step: dict) -> None:
        """Query a node's status."""
        key = step["key"]
        parsed = ke.parse_key_expr(key)
        if parsed and "node_id" in parsed:
            result = self._zenoh.query_node_status(parsed["zone"], parsed["node_id"])
            if result:
                logger.info("  Query result from %s: %s", key, result)
            else:
                logger.warning("  Query timeout: %s", key)
        else:
            logger.warning("  Cannot parse query key: %s", key)

    def _action_log(self, step: dict) -> None:
        """Log a message."""
        message = step.get("message", "")
        logger.info("  [LOG] %s", message)

    def _setup_value_tracking(self, scenario: Scenario) -> None:
        """Subscribe to all sensor keys in the scenario for value tracking."""
        self._zenoh.subscribe_sensors(callback=self._on_sensor_value)

    def _on_sensor_value(self, key_expr: str, sensor_data: SensorData) -> None:
        """Track latest sensor values for wait_sensor conditions."""
        self._latest_values[key_expr] = sensor_data.value


def list_scenarios(scenarios_dir: str | Path) -> list[dict]:
    """List all available scenario files."""
    scenarios_dir = Path(scenarios_dir)
    result = []
    for path in sorted(scenarios_dir.glob("*.yaml")):
        try:
            scenario = Scenario.from_yaml(path)
            result.append({
                "name": scenario.name,
                "file": path.name,
                "description": scenario.description,
                "zone": scenario.zone,
                "nodes": len(scenario.nodes),
                "steps": len(scenario.sequence),
            })
        except Exception as e:
            result.append({"name": path.stem, "file": path.name, "error": str(e)})
    return result
