"""Main entrypoint for the Zenoh 10BASE-T1S master controller.

PRD Section 6: System startup sequence.
Can be run directly or via the CLI:
  python -m src.master.main
  zenoh-t1s-master start
"""

from __future__ import annotations

import logging
import sys

from src.master.cli import app


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the master application."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> None:
    setup_logging()
    app()


if __name__ == "__main__":
    main()
