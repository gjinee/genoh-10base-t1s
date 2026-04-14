"""Unified launcher for Master + Slave GUI simulators.

Usage:
    python -m gui.run                       # Both GUIs, SIM mode
    python -m gui.run --mode hw             # Both GUIs, HW mode
    python -m gui.run --master-only         # Master only
    python -m gui.run --slave-only          # Slave only
    python -m gui.run --master-port 8010 --slave-port 8020
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

import uvicorn

from gui.common.sim_engine import get_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("gui.run")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="10BASE-T1S Vehicle GUI Simulator")
    p.add_argument("--mode", choices=["sim", "hw"], default="sim",
                   help="sim = in-memory simulation, hw = real 10BASE-T1S bus")
    p.add_argument("--master-port", type=int, default=8010)
    p.add_argument("--slave-port", type=int, default=8020)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--master-only", action="store_true")
    p.add_argument("--slave-only", action="store_true")
    p.add_argument("--scenario", default="", help="Auto-load scenario on start")
    return p.parse_args()


async def run_server(app_path: str, host: str, port: int) -> None:
    config = uvicorn.Config(app_path, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main() -> None:
    args = parse_args()

    # Initialize shared engine
    engine = get_engine(args.mode)

    if args.scenario:
        engine.load_scenario(args.scenario)

    tasks = []

    if not args.slave_only:
        logger.info("Starting Master GUI on http://%s:%d", args.host, args.master_port)
        tasks.append(run_server("gui.master.app:app", args.host, args.master_port))

    if not args.master_only:
        logger.info("Starting Slave GUI on http://%s:%d", args.host, args.slave_port)
        tasks.append(run_server("gui.slave.app:app", args.host, args.slave_port))

    if not tasks:
        logger.error("No servers to start. Use --master-only or --slave-only, not both exclusions.")
        sys.exit(1)

    logger.info("Mode: %s", args.mode.upper())
    logger.info("="*60)
    if not args.slave_only:
        logger.info("  Master GUI: http://localhost:%d", args.master_port)
    if not args.master_only:
        logger.info("  Slave GUI:  http://localhost:%d", args.slave_port)
    logger.info("="*60)

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
