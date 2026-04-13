"""Tests for scenario YAML parser (PRD FR-008)."""

from pathlib import Path

from src.master.scenario_runner import Scenario, list_scenarios, OPERATORS

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "config" / "scenarios"


class TestScenarioParser:
    def test_load_door_zone(self):
        scenario = Scenario.from_yaml(SCENARIOS_DIR / "door_zone.yaml")
        assert scenario.name == "door_zone_control"
        assert scenario.zone == "front_left"
        assert len(scenario.nodes) == 3
        assert len(scenario.sequence) == 7

    def test_load_lighting_control(self):
        scenario = Scenario.from_yaml(SCENARIOS_DIR / "lighting_control.yaml")
        assert scenario.name == "lighting_control"
        assert scenario.zone == "front"
        assert len(scenario.nodes) == 2
        assert len(scenario.sequence) == 8

    def test_load_sensor_polling(self):
        scenario = Scenario.from_yaml(SCENARIOS_DIR / "sensor_polling.yaml")
        assert scenario.name == "sensor_polling"
        assert scenario.zone == "all"
        assert len(scenario.nodes) == 4
        assert scenario.interval_ms == 1000

    def test_door_zone_nodes(self):
        scenario = Scenario.from_yaml(SCENARIOS_DIR / "door_zone.yaml")
        node_ids = [n["node_id"] for n in scenario.nodes]
        assert "1" in node_ids
        assert "2" in node_ids

    def test_door_zone_sequence_actions(self):
        scenario = Scenario.from_yaml(SCENARIOS_DIR / "door_zone.yaml")
        actions = [s["action"] for s in scenario.sequence]
        assert "wait_sensor" in actions
        assert "publish" in actions
        assert "log" in actions
        assert "query" in actions

    def test_door_zone_condition(self):
        """Verify condition uses simple comparison operators only (PRD 4.3)."""
        scenario = Scenario.from_yaml(SCENARIOS_DIR / "door_zone.yaml")
        wait_steps = [s for s in scenario.sequence if s["action"] == "wait_sensor"]
        assert len(wait_steps) >= 1
        cond = wait_steps[0]["condition"]
        assert cond["operator"] in OPERATORS


class TestListScenarios:
    def test_list_all(self):
        scenarios = list_scenarios(SCENARIOS_DIR)
        names = [s["name"] for s in scenarios]
        assert "door_zone_control" in names
        assert "lighting_control" in names
        assert "sensor_polling" in names

    def test_list_has_metadata(self):
        scenarios = list_scenarios(SCENARIOS_DIR)
        for s in scenarios:
            assert "name" in s
            assert "file" in s
            assert "description" in s


class TestOperators:
    def test_all_operators_defined(self):
        """PRD 4.3: simple comparison operators only."""
        for op in ["<", ">", "<=", ">=", "==", "!="]:
            assert op in OPERATORS

    def test_operator_evaluation(self):
        assert OPERATORS["<"](10, 30) is True
        assert OPERATORS[">"](100, 30) is True
        assert OPERATORS["=="](5, 5) is True
        assert OPERATORS["!="](5, 6) is True
        assert OPERATORS["<="](5, 5) is True
        assert OPERATORS[">="](6, 5) is True
