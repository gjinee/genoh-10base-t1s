"""Simulation harness configuration constants."""

from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS_DIR = PROJECT_ROOT / "config" / "scenarios"
SRC_DIR = PROJECT_ROOT / "src"

# Default simulation parameters
DEFAULT_SCENARIO = "door_zone"
DEFAULT_INTERFACE = "eth1"
DEFAULT_PLCA_NODE_COUNT = 8
DEFAULT_PLCA_TO_TIMER = 0x20

# Model assignments for agents
MODELS = {
    "master-controller": "claude-sonnet-4-6",
    "slave-simulator": "claude-haiku-4-5-20251001",
    "network-monitor": "claude-sonnet-4-6",
    "agent-evaluator": "claude-opus-4-6",
}

# Zenoh defaults
ZENOH_ROUTER_ENDPOINT = "tcp/192.168.1.1:7447"
ZENOH_SCOUTING_MULTICAST = "224.0.0.224:7446"
