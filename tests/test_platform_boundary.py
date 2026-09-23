"""The engine never imports the platform.

`docs/scaling.md` rests on the engine not knowing who is calling. The import
direction is what enforces that: `vp/platform/` may import the engine, and
nothing else under `vp/` may import the platform. `vp/cli.py` is the one
exception, as the composition root, and it imports the platform only
inside the `serve` and `db` commands.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "vp"
PLATFORM = PACKAGE / "platform"
COMPOSITION_ROOT = PACKAGE / "cli.py"


def _imports_platform(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "vp.platform"
        ):
            return True
        if isinstance(node, ast.Import) and any(
            a.name.startswith("vp.platform") for a in node.names
        ):
            return True
    return False


def test_no_engine_module_imports_the_platform() -> None:
    offenders = [
        str(path.relative_to(PACKAGE.parent))
        for path in sorted(PACKAGE.rglob("*.py"))
        if not path.is_relative_to(PLATFORM)
        and path != COMPOSITION_ROOT
        and _imports_platform(ast.parse(path.read_text()))
    ]
    assert offenders == [], f"the engine must not import the platform: {offenders}"


def test_the_composition_root_imports_it_only_lazily() -> None:
    """A top-level import would load the platform for every engine command."""
    tree = ast.parse(COMPOSITION_ROOT.read_text())
    top_level = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
    assert not any(_imports_platform(ast.Module(body=[n], type_ignores=[])) for n in top_level)
