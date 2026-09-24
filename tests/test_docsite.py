"""The documentation site (plan, Phase 23; docs/site.md): it builds from
the repository with no broken link, anchor or command, publishes every
docs page with its markdown twin, and its checks catch what they claim to."""

from __future__ import annotations

import json
from pathlib import Path

from vp.cli import _site, build_parser
from vp.docsite.build import Rendered, _check_commands, check
from vp.docsite.pages import Page

ROOT = Path(__file__).resolve().parent.parent


def test_the_site_builds_clean_and_publishes_every_doc(tmp_path: Path) -> None:
    out = tmp_path / "site"
    _site(out, build_parser())  # exits 1 on any problem
    for doc in (ROOT / "docs").glob("*.md"):
        folder = out / "docs" if doc.stem == "index" else out / "docs" / doc.stem
        assert (folder / "index.html").exists() and (folder / "index.md").exists()
    for page in (
        "reference/cli",
        "reference/api",
        "reference/mcp",
        "roadmap",
        "signals",
    ):
        assert (out / page / "index.html").exists()
    assert "<math" in (out / "docs/sizing/index.html").read_text()
    index = json.loads((out / "search.json").read_text())
    assert any(p["t"] == "Edge, Fees and Sizing" for p in index)
    llms = (out / "llms.txt").read_text()
    assert "docs/security/index.md" in llms and "reports/phase21_scale/index.md" in llms
    # Everything the pages load is on the site: no third-party request.
    assert "https://" not in "".join(
        line
        for f in out.rglob("*.html")
        for line in f.read_text().splitlines()
        if "<link" in line or "<script" in line
    )


def test_a_stale_command_is_caught() -> None:
    def page(md: str, runnable: list[str], named: list[str]) -> Rendered:
        p = Page("x", "x", "Docs", md, "docs/x.md", "")
        return Rendered(
            p,
            "",
            [],
            "",
            [(True, c) for c in runnable] + [(False, c) for c in named],
            [],
        )

    parser = build_parser()
    ok = page(
        "",
        ["backtest --domain epl --forecasters market"],
        ["backtest", "admin unit-costs"],
    )
    assert _check_commands(parser, [ok]) == []
    bad = page("", ["backtest --domian epl"], ["nonsense", "backtest --nope"])
    problems = _check_commands(parser, [bad])
    assert len(problems) == 3, problems


def test_a_broken_link_or_anchor_is_caught(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "index.html").write_text(
        '<h2 id="here">x</h2><a href="#here">ok</a><a href="#gone">no</a>'
        '<a href="../b/">no</a><a href="https://example.com">out</a>'
    )
    problems = check(tmp_path)
    assert len(problems) == 2 and "#gone" in problems[0] + problems[1]
