"""Scenario management MCP tools.

Loads and manages YAML simulation scenarios for the 10BASE-T1S Zenoh network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from claude_agent_sdk import tool

_SCENARIOS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "scenarios"

# Cache loaded scenarios
_loaded_scenarios: dict[str, dict] = {}


@tool(
    "load_scenario",
    "Load a simulation scenario from YAML. Returns the parsed scenario "
    "with nodes, sequences, and configuration for the 10BASE-T1S simulation.",
    {"scenario_name": str},
)
async def load_scenario(args: dict[str, Any]) -> dict[str, Any]:
    name = args["scenario_name"]

    # Try exact filename or with .yaml extension
    candidates = [
        _SCENARIOS_DIR / name,
        _SCENARIOS_DIR / f"{name}.yaml",
        _SCENARIOS_DIR / f"{name}.yml",
    ]

    for path in candidates:
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                scenario = yaml.safe_load(f)

            _loaded_scenarios[name] = scenario

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "status": "loaded",
                                "scenario_name": scenario.get("name", name),
                                "description": scenario.get("description", ""),
                                "zone": scenario.get("zone", "all"),
                                "node_count": len(scenario.get("nodes", [])),
                                "step_count": len(scenario.get("sequence", [])),
                                "scenario": scenario,
                            }
                        ),
                    }
                ]
            }

    available = [f.stem for f in _SCENARIOS_DIR.glob("*.yaml")]
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "status": "not_found",
                        "scenario_name": name,
                        "available": available,
                        "search_dir": str(_SCENARIOS_DIR),
                    }
                ),
            }
        ]
    }


@tool(
    "list_scenarios",
    "List all available simulation scenarios in the config/scenarios directory.",
    {},
)
async def list_scenarios(args: dict[str, Any]) -> dict[str, Any]:
    scenarios = []

    for path in sorted(_SCENARIOS_DIR.glob("*.yaml")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            scenarios.append(
                {
                    "name": data.get("name", path.stem),
                    "file": path.name,
                    "description": data.get("description", ""),
                    "zone": data.get("zone", "all"),
                    "node_count": len(data.get("nodes", [])),
                    "step_count": len(data.get("sequence", [])),
                }
            )
        except Exception as e:
            scenarios.append(
                {
                    "name": path.stem,
                    "file": path.name,
                    "error": str(e),
                }
            )

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "scenario_count": len(scenarios),
                        "scenarios_dir": str(_SCENARIOS_DIR),
                        "scenarios": scenarios,
                    }
                ),
            }
        ]
    }


def get_all_tools():
    """Return all scenario tools for MCP server creation."""
    return [load_scenario, list_scenarios]
