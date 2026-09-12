"""Command-line entry point for vibe-predict.

Subcommands are added phase by phase; at Phase 6 the CLI only reports the
package version so that the ``vp`` entry point resolves and can be smoke-tested.
"""

from __future__ import annotations

import argparse
from importlib.metadata import version


def main() -> None:
    """Parse arguments and dispatch. Exits with the parser's help when idle."""
    parser = argparse.ArgumentParser(
        prog="vp",
        description="vibe-predict: LLM forecasting of Polymarket binary contracts.",
    )
    parser.add_argument(
        "--version", action="version", version=f"vp {version('vibe-predict')}"
    )
    parser.parse_args()
    parser.print_help()
