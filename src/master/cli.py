"""CLI interface for the Zenoh 10BASE-T1S master controller.

Implements PRD Section 8.1 CLI commands using Typer.

Usage:
  zenoh-t1s-master start [--config config.yaml] [--scenario door_zone]
  zenoh-t1s-master nodes list
  zenoh-t1s-master nodes status <node_id>
  zenoh-t1s-master diag plca
  zenoh-t1s-master diag traffic
  zenoh-t1s-master scenario run <name>
  zenoh-t1s-master scenario list
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="zenoh-t1s-master",
    help="Zenoh 10BASE-T1S Automotive Master Controller",
)
nodes_app = typer.Typer(help="Node management commands")
diag_app = typer.Typer(help="Diagnostics commands")
scenario_app = typer.Typer(help="Scenario commands")

app.add_typer(nodes_app, name="nodes")
app.add_typer(diag_app, name="diag")
app.add_typer(scenario_app, name="scenario")

console = Console()

SCENARIOS_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "scenarios"


# --- Main commands ---

@app.command()
def start(
    config: str = typer.Option("config/master_config.json5", help="zenohd config path"),
    scenario: str | None = typer.Option(None, help="Scenario to auto-run"),
    interface: str = typer.Option("eth1", help="10BASE-T1S network interface"),
    ip_addr: str = typer.Option("192.168.1.1/24", help="Master IP address"),
    router: str = typer.Option("tcp/127.0.0.1:7447", help="Zenoh router endpoint"),
) -> None:
    """Start the master controller (PLCA + Zenoh + scenario)."""
    asyncio.run(_start_master(config, scenario, interface, ip_addr, router))


async def _start_master(
    config: str,
    scenario_name: str | None,
    interface: str,
    ip_addr: str,
    router: str,
) -> None:
    from src.common.models import PLCAConfig
    from src.master.diagnostics import DiagnosticsCollector
    from src.master.network_setup import NetworkSetup
    from src.master.node_manager import NodeManager
    from src.master.scenario_runner import Scenario, ScenarioRunner
    from src.master.zenoh_master import ZenohMaster

    # Step 1-2: Network + PLCA initialization
    plca_config = PLCAConfig(interface=interface)
    network = NetworkSetup(plca_config)

    console.print(f"[bold]Initializing 10BASE-T1S on {interface}...[/bold]")
    if not await network.initialize(ip_addr):
        console.print("[red]Network initialization failed[/red]")
        raise typer.Exit(1)
    console.print("[green]Network initialized[/green]")

    # Step 3: Zenoh session
    console.print(f"[bold]Connecting to Zenoh router: {router}[/bold]")
    zenoh_master = ZenohMaster(router_endpoint=router)
    zenoh_master.open()
    console.print(f"[green]Zenoh session open: {zenoh_master.session.zid()}[/green]")

    # Step 4: Node manager + discovery
    node_mgr = NodeManager(zenoh_master.session)
    node_mgr.start_discovery(
        on_online=lambda n: console.print(f"[green]Node ONLINE: {n.node_id}[/green]"),
        on_offline=lambda n: console.print(f"[red]Node OFFLINE: {n.node_id}[/red]"),
    )

    # Step 5: Diagnostics
    diagnostics = DiagnosticsCollector(network, node_mgr)

    # Step 6: Scenario (optional)
    if scenario_name:
        scenario_path = SCENARIOS_DIR / f"{scenario_name}.yaml"
        if not scenario_path.exists():
            console.print(f"[red]Scenario not found: {scenario_path}[/red]")
        else:
            scenario = Scenario.from_yaml(scenario_path)
            runner = ScenarioRunner(zenoh_master)
            console.print(f"[bold]Running scenario: {scenario.name}[/bold]")
            await runner.run(scenario)

    # Run diagnostics monitor
    console.print("[bold]Entering monitor mode (Ctrl+C to stop)...[/bold]")
    try:
        await diagnostics.monitor_loop(interval_sec=10.0)
    except KeyboardInterrupt:
        pass
    finally:
        node_mgr.stop_discovery()
        zenoh_master.close()
        console.print("[bold]Shutdown complete[/bold]")


# --- Node commands ---

@nodes_app.command("list")
def nodes_list(
    router: str = typer.Option("tcp/127.0.0.1:7447", help="Zenoh router endpoint"),
) -> None:
    """List connected slave nodes."""
    from src.master.node_manager import NodeManager
    from src.master.zenoh_master import ZenohMaster

    with ZenohMaster(router_endpoint=router) as zm:
        mgr = NodeManager(zm.session)
        mgr.start_discovery()

        import time
        time.sleep(3)  # Wait for discovery

        table = Table(title="Connected Nodes")
        table.add_column("Node ID")
        table.add_column("Zone")
        table.add_column("PLCA ID")
        table.add_column("Role")
        table.add_column("Status")

        for node_id, info in mgr.nodes.items():
            status = "[green]ONLINE[/green]" if info.alive else "[red]OFFLINE[/red]"
            table.add_row(
                node_id, info.zone, str(info.plca_node_id),
                info.role.value, status,
            )

        console.print(table)
        mgr.stop_discovery()


@nodes_app.command("status")
def nodes_status(
    node_id: str = typer.Argument(help="Node ID to query"),
    zone: str = typer.Option("*", help="Node zone"),
    router: str = typer.Option("tcp/127.0.0.1:7447", help="Zenoh router endpoint"),
) -> None:
    """Query a specific node's status."""
    from src.master.zenoh_master import ZenohMaster

    with ZenohMaster(router_endpoint=router) as zm:
        result = zm.query_node_status(zone, node_id)
        if result:
            console.print_json(data=result)
        else:
            console.print(f"[red]No response from node {node_id}[/red]")


# --- Diagnostics commands ---

@diag_app.command("plca")
def diag_plca(
    interface: str = typer.Option("eth1", help="Network interface"),
) -> None:
    """Show PLCA status."""
    from src.common.models import PLCAConfig
    from src.master.network_setup import NetworkSetup

    config = PLCAConfig(interface=interface)
    network = NetworkSetup(config)
    status = asyncio.run(network.get_plca_status())

    table = Table(title=f"PLCA Status ({interface})")
    table.add_column("Parameter")
    table.add_column("Value")
    table.add_row("Supported", str(status.supported))
    table.add_row("Enabled", str(status.enabled))
    table.add_row("Node ID", str(status.node_id))
    table.add_row("Node Count", str(status.node_count))
    table.add_row("TO Timer", str(status.to_timer))
    table.add_row("Beacon Active", str(status.beacon_active))
    table.add_row("Worst-case Cycle", f"{config.worst_case_cycle_ms} ms")
    table.add_row("Min Cycle", f"{config.min_cycle_us} µs")
    console.print(table)


@diag_app.command("network")
def diag_network(
    interface: str = typer.Option("eth1", help="Network interface"),
) -> None:
    """Show network interface status."""
    from src.common.models import PLCAConfig
    from src.master.network_setup import NetworkSetup

    config = PLCAConfig(interface=interface)
    network = NetworkSetup(config)
    link_up = asyncio.run(network.get_link_status())
    detected = asyncio.run(network.detect_interface())

    console.print(f"Interface: {interface}")
    console.print(f"Detected: {'[green]YES[/green]' if detected else '[red]NO[/red]'}")
    console.print(f"Link: {'[green]UP[/green]' if link_up else '[red]DOWN[/red]'}")


# --- Scenario commands ---

@scenario_app.command("list")
def scenario_list() -> None:
    """List available scenarios."""
    from src.master.scenario_runner import list_scenarios

    scenarios = list_scenarios(SCENARIOS_DIR)
    table = Table(title="Available Scenarios")
    table.add_column("Name")
    table.add_column("File")
    table.add_column("Zone")
    table.add_column("Nodes")
    table.add_column("Steps")
    table.add_column("Description")

    for s in scenarios:
        if "error" in s:
            table.add_row(s["name"], s["file"], "", "", "", f"[red]{s['error']}[/red]")
        else:
            table.add_row(
                s["name"], s["file"], s["zone"],
                str(s["nodes"]), str(s["steps"]), s["description"],
            )
    console.print(table)


@scenario_app.command("run")
def scenario_run(
    name: str = typer.Argument(help="Scenario name"),
    router: str = typer.Option("tcp/127.0.0.1:7447", help="Zenoh router endpoint"),
    interface: str = typer.Option("eth1", help="10BASE-T1S interface"),
) -> None:
    """Run a simulation scenario."""
    scenario_path = SCENARIOS_DIR / f"{name}.yaml"
    if not scenario_path.exists():
        console.print(f"[red]Scenario not found: {name}[/red]")
        raise typer.Exit(1)

    asyncio.run(_start_master(
        config="config/master_config.json5",
        scenario_name=name,
        interface=interface,
        ip_addr="192.168.1.1/24",
        router=router,
    ))


if __name__ == "__main__":
    app()
