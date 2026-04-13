"""Simulation harness orchestrator.

Subagent pattern: orchestrator delegates to master-controller, slave-simulator,
network-monitor, and agent-evaluator via Claude Agent SDK.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, query

from sim_harness.agents.definitions import get_all_agents
from sim_harness.config import PROJECT_ROOT, SCENARIOS_DIR
from sim_harness.tools.plca_tools import get_all_tools as plca_tools
from sim_harness.tools.scenario_tools import get_all_tools as scenario_tools
from sim_harness.tools.zenoh_tools import get_all_tools as zenoh_tools


def _create_mcp_servers() -> dict:
    """Create the 3 MCP tool servers."""
    return {
        "zenoh": create_sdk_mcp_server(
            name="zenoh",
            version="1.0.0",
            tools=zenoh_tools(),
        ),
        "plca": create_sdk_mcp_server(
            name="plca",
            version="1.0.0",
            tools=plca_tools(),
        ),
        "scenario": create_sdk_mcp_server(
            name="scenario",
            version="1.0.0",
            tools=scenario_tools(),
        ),
    }


def _build_simulation_prompt(scenario_name: str) -> str:
    """Build the orchestrator prompt for a given scenario."""
    return f"""\
You are the **Simulation Orchestrator** for a 10BASE-T1S Zenoh automotive network.

## Simulation Scenario: {scenario_name}

Execute the following workflow step by step:

### Phase 1: PLCA Initialization
Use the **master-controller** agent to:
1. Check PLCA status (should be coordinator, beacon active)
2. Configure PLCA if needed (Node ID 0, node count from scenario)

### Phase 2: Scenario Loading
Use the scenario tools directly to:
1. Load the "{scenario_name}" scenario
2. Parse node definitions and sequence steps

### Phase 3: Slave Node Registration
Use the **slave-simulator** agent to:
1. Register all nodes defined in the scenario
2. Start sensor data publishing for sensor nodes
3. Set up actuator subscriptions for actuator nodes

### Phase 4: Master Execution
Use the **master-controller** agent to:
1. Subscribe to all sensor key expressions from the scenario
2. Execute the scenario sequence steps in order
3. Publish actuator commands as specified
4. Query node status at each step

### Phase 5: Network Monitoring
Use the **network-monitor** agent to:
1. Check PLCA health (beacon, collisions)
2. Verify all expected nodes are online
3. Analyze traffic flow (messages per key expression)
4. Generate a diagnostic report

### Phase 6: Agent Evaluation
Use the **agent-evaluator** agent to:
1. Review the simulation transcript from phases 1-5
2. Evaluate each agent (master-controller, slave-simulator, network-monitor)
3. Score each agent on protocol compliance, correctness, and output quality
4. Generate a final evaluation report with grades and recommendations

## Important Rules
- Always complete Phase 1 before Phase 3
- Phase 2 can run in parallel with Phase 1
- Phase 4 depends on Phase 3 completion
- Phase 5 can run during or after Phase 4
- Phase 6 must run after all other phases complete
- Report any errors or anomalies immediately
"""


async def run_simulation(scenario_name: str, max_budget_usd: float = 5.0) -> None:
    """Run a complete simulation for the given scenario.

    Args:
        scenario_name: Name of the scenario YAML file (without extension).
        max_budget_usd: Maximum budget in USD for the simulation run.
    """
    mcp_servers = _create_mcp_servers()
    agents = get_all_agents()

    # Build allowed tools list
    allowed_tools = [
        # Zenoh MCP tools
        "mcp__zenoh__zenoh_publish",
        "mcp__zenoh__zenoh_subscribe",
        "mcp__zenoh__zenoh_query",
        "mcp__zenoh__zenoh_list_nodes",
        "mcp__zenoh__zenoh_register_node",
        # PLCA MCP tools
        "mcp__plca__plca_get_status",
        "mcp__plca__plca_set_config",
        # Scenario MCP tools
        "mcp__scenario__load_scenario",
        "mcp__scenario__list_scenarios",
        # Built-in tools
        "Read",
        "Bash",
        "Agent",  # Required for subagent invocation
    ]

    options = ClaudeAgentOptions(
        mcp_servers=mcp_servers,
        allowed_tools=allowed_tools,
        agents=agents,
        system_prompt=(
            "You are running a 10BASE-T1S Zenoh automotive network simulation. "
            "Delegate specialized tasks to subagents. Coordinate the workflow "
            "and ensure all phases complete successfully."
        ),
        cwd=str(PROJECT_ROOT),
        model="claude-sonnet-4-6",
        max_turns=30,
        max_budget_usd=max_budget_usd,
    )

    prompt = _build_simulation_prompt(scenario_name)

    print(f"=== Starting simulation: {scenario_name} ===")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Scenarios dir: {SCENARIOS_DIR}")
    print()

    async for message in query(prompt=prompt, options=options):
        # Print assistant messages
        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    print(block.text)
                elif hasattr(block, "type") and block.type == "tool_use":
                    print(f"  [Tool] {block.name}({json.dumps(block.input)[:120]}...)")

        # Print final result
        if hasattr(message, "result"):
            print("\n=== Simulation Complete ===")
            print(message.result)

    print("\n=== Simulation session ended ===")
