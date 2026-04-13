"""Simulation harness CLI entrypoint.

Usage:
    python -m sim_harness.main --scenario door_zone
    python -m sim_harness.main --scenario lighting_control
    python -m sim_harness.main --scenario sensor_polling
    python -m sim_harness.main --list
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sim_harness.config import DEFAULT_SCENARIO, SCENARIOS_DIR


def _list_scenarios() -> None:
    """Print available scenarios."""
    print("Available scenarios:")
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        print(f"  - {path.stem}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="10BASE-T1S Zenoh Simulation Harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python -m sim_harness.main --scenario door_zone
  python -m sim_harness.main --scenario sensor_polling --budget 3.0
  python -m sim_harness.main --list
        """,
    )
    parser.add_argument(
        "--scenario",
        type=str,
        default=DEFAULT_SCENARIO,
        help=f"Scenario name to run (default: {DEFAULT_SCENARIO})",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios and exit",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=5.0,
        help="Maximum budget in USD for the simulation (default: 5.0)",
    )

    args = parser.parse_args()

    if args.list:
        _list_scenarios()
        sys.exit(0)

    # Verify scenario exists
    scenario_path = SCENARIOS_DIR / f"{args.scenario}.yaml"
    if not scenario_path.is_file():
        print(f"Error: Scenario '{args.scenario}' not found at {scenario_path}")
        _list_scenarios()
        sys.exit(1)

    # Import here to avoid import errors if SDK not installed
    from sim_harness.orchestrator import run_simulation

    asyncio.run(run_simulation(args.scenario, max_budget_usd=args.budget))


if __name__ == "__main__":
    main()
