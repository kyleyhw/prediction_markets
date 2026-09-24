"""The documentation site (plan, Phase 23; docs/site.md).

`collect` gathers every page from its source; `build.build` renders and
checks them. The composition root (`vp site build`) passes in what only
the platform knows, the OpenAPI document and the MCP tool list, so this
package imports nothing from `vp/platform`.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from vp.docsite import pages as P


def collect(
    root: Path,
    parser: argparse.ArgumentParser,
    openapi: dict[str, Any],
    mcp_tools: tuple[str, ...],
    signal_manifest: list[dict[str, Any]],
) -> list[P.Page]:
    reference = [
        P.cli_reference(root, parser),
        P.api_reference(root, openapi),
        P.mcp_reference(root, mcp_tools),
        P.glossary(root),
    ]
    return [
        P.home(root),
        *P.folder(root, "tutorials", "Tutorials"),
        *P.docs(root),
        *P.learn(root),
        *P.folder(root, "lab", "Lab"),
        *P.signals(root, signal_manifest),
        P.reference_index(root, reference),
        *reference,
        *P.reports(root),
        P.roadmap(root),
    ]
