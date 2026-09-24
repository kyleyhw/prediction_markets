"""The gates a contribution passes in CI (plan, task 90; CONTRIBUTING.md).

* The reference project's name appears only where attribution or design
  notes need it, never on a product surface (docs/vibe_trading.md § 9).
* The documentation carries no market-data dumps: no data files, and no
  table or code block longer than `MAX_BLOCK` lines.
Secrets are the detect-secrets hook's job; sign-off is the pull-request
job's (`.github/workflows/ci.yml`).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"Vibe[- ]Trading|HKUDS", re.IGNORECASE)
MAX_BLOCK = 60

# Where the name may appear, and why.
ALLOWED = {
    # The record § 9 names: provenance, the review, the licence notice, the
    # plan's references and the README's provenance lines.
    "NOTICE",
    "PROJECT_PLAN.md",
    "README.md",
    "docs/provenance.md",
    "docs/vibe_trading.md",
    # Developer design notes that cite a borrowed idea.
    "CLAUDE.md",
    "docs/index.md",
    "docs/forecasters.md",
    "docs/scaling.md",
    "tests/reports/phase6_restructure.md",
    "vp/forecast/llm.py",
    "vp/forecast/registry.py",
    # The ported modules' attribution, which the MIT licence requires.
    "vp/backtest/bankroll.py",
    "vp/venues/_http.py",
    "vp/venues/polymarket.py",
    # This file.
    "tests/test_contribution_gates.py",
}
SKIP = {".git", ".venv", "archive", "node_modules", "__pycache__", ".ruff_cache"}
TEXT = {
    ".py",
    ".md",
    ".js",
    ".json",
    ".html",
    ".css",
    ".yaml",
    ".yml",
    ".toml",
    ".sql",
    "",
}


def _files() -> list[Path]:
    return [
        p
        for p in ROOT.rglob("*")
        if p.is_file()
        and not SKIP & set(p.relative_to(ROOT).parts)
        and p.suffix in TEXT
        and p.stat().st_size < 2_000_000
    ]


def test_the_reference_project_is_named_only_where_allowed() -> None:
    found = sorted(
        str(p.relative_to(ROOT))
        for p in _files()
        if NAME.search(p.read_text(errors="ignore"))
    )
    assert set(found) <= ALLOWED, (
        f"named outside the allowed files: {set(found) - ALLOWED}"
    )


def test_no_product_surface_names_it() -> None:
    surfaces = [ROOT / "vp" / "ui" / "static", ROOT / "vp" / "platform"]
    named = [
        str(p.relative_to(ROOT))
        for base in surfaces
        for p in base.rglob("*")
        if p.is_file()
        and p.suffix in TEXT
        and NAME.search(p.read_text(errors="ignore"))
    ]
    assert named == []


def test_the_docs_carry_no_data_dumps() -> None:
    docs = ROOT / "docs"
    data = [
        p
        for p in docs.rglob("*")
        if p.suffix in {".csv", ".parquet", ".json", ".jsonl"}
    ]
    assert data == [], f"data files in docs: {data}"
    for path in docs.rglob("*.md"):
        table = code = 0
        inside = False
        for line in path.read_text().splitlines():
            if line.startswith("```"):
                inside, code = not inside, 0
                continue
            code = code + 1 if inside else 0
            table = table + 1 if line.startswith("|") else 0
            assert table <= MAX_BLOCK and code <= MAX_BLOCK, (
                f"{path.relative_to(ROOT)} has a block longer than {MAX_BLOCK} lines"
            )
