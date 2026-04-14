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
from sim_harness.tools.safety_tools import get_all_tools as safety_tools
from sim_harness.tools.scenario_tools import get_all_tools as scenario_tools
from sim_harness.tools.security_tools import get_all_tools as security_tools
from sim_harness.tools.zenoh_tools import get_all_tools as zenoh_tools


def _create_mcp_servers() -> dict:
    """Create the 5 MCP tool servers (zenoh, plca, scenario, safety, security)."""
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
        "safety": create_sdk_mcp_server(
            name="safety",
            version="1.0.0",
            tools=safety_tools(),
        ),
        "security": create_sdk_mcp_server(
            name="security",
            version="1.0.0",
            tools=security_tools(),
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

### Phase 2: Scenario Loading + Security Setup
Use the scenario tools and security tools to:
1. Load the "{scenario_name}" scenario
2. Parse node definitions and sequence steps
3. Register all nodes with ACL (security_register_node)
4. Derive per-node HMAC keys

### Phase 3: Slave Node Registration (with Safety/Security)
Use the **slave-simulator** agent to:
1. Register all nodes (Zenoh + security role)
2. Start publishing E2E-protected sensor data (safety_e2e_encode)
3. Set up actuator subscriptions (with SecOC verification)

### Phase 4: Master Execution (Safety-Aware)
Use the **master-controller** agent to:
1. Run self-test (verify E2E, FSM, watchdog)
2. Subscribe to all sensor key expressions
3. Execute main loop with flow monitor checkpoints:
   a. Process sensors (CP_SENSOR) — E2E decode + verify
   b. Process actuators (CP_ACTUATOR) — SecOC encode + publish
   c. Process queries (CP_QUERY) — node status
   d. Collect diagnostics (CP_DIAG) — DTC/safety log
4. Kick watchdog after each cycle
5. Verify flow at end of cycle

### Phase 5: Security Testing
Use the **slave-simulator** agent (as attacker) to:
1. Send spoofed sensor message (wrong HMAC key)
2. Replay a previously valid message
3. Flood with excessive messages
4. Attempt unauthorized key expression publish
Then use the **network-monitor** agent to:
5. Verify IDS alerts were generated for each attack
6. Verify security log chain integrity

### Phase 6: Fault Injection
Use the **slave-simulator** agent to:
1. Simulate node going offline (stop publishing)
2. Send messages with corrupted CRC
3. Send messages with large sequence gaps
Then use the **master-controller** agent to:
4. Verify Safety FSM transitions (NORMAL→DEGRADED→SAFE_STATE)
5. Apply safe actions to actuators
6. Simulate recovery and verify FSM returns to NORMAL

### Phase 7: Network Monitoring + Diagnostics
Use the **network-monitor** agent to:
1. Check PLCA health (beacon, collisions)
2. Review safety state and DTC codes
3. Review IDS alerts and security log
4. Generate comprehensive diagnostic report

### Phase 8: Agent Evaluation
Use the **agent-evaluator** agent to:
1. Review the simulation transcript from phases 1-7
2. Evaluate each agent on safety/security compliance
3. Score on E2E protection, SecOC auth, IDS detection, FSM correctness
4. Generate final evaluation report with grades

## Important Rules
- Always complete Phase 1 before Phase 3
- Phase 2 can run in parallel with Phase 1
- Phase 4 depends on Phase 3 completion
- Phase 5 depends on Phase 4 (needs baseline traffic)
- Phase 6 depends on Phase 4 (needs normal operation first)
- Phase 7 can run during or after Phase 5-6
- Phase 8 must run after all other phases complete
- All messages MUST use E2E protection
- Actuator commands MUST use SecOC
- Report safety state transitions immediately
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
        # Safety MCP tools
        "mcp__safety__safety_e2e_encode",
        "mcp__safety__safety_e2e_decode",
        "mcp__safety__safety_get_state",
        "mcp__safety__safety_report_fault",
        "mcp__safety__safety_report_recovery",
        "mcp__safety__safety_get_safe_action",
        "mcp__safety__safety_flow_checkpoint",
        "mcp__safety__safety_kick_watchdog",
        # Security MCP tools
        "mcp__security__security_secoc_encode",
        "mcp__security__security_secoc_decode",
        "mcp__security__security_ids_check",
        "mcp__security__security_acl_check",
        "mcp__security__security_register_node",
        "mcp__security__security_get_alerts",
        "mcp__security__security_verify_chain",
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
