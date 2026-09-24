"""The page's message catalogue against the code that uses it.

The interface takes every word from `vp/ui/static/app/locales/en.json`
(docs/interface.md). A key used in the code but missing from the catalogue
would show the key itself to a person, so every literal key is checked, and
the keys the views build from a fixed list are expanded and checked too.
Messages are trusted text inserted into HTML and attributes, so none may
carry a straight double quote or an angle bracket that starts a tag.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "vp" / "ui" / "static" / "app"
CATALOGUE = json.loads((APP / "locales" / "en.json").read_text())
SOURCES = {p: p.read_text() for p in APP.rglob("*.js")}


def lookup(key: str) -> object:
    node: object = CATALOGUE
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def is_message(node: object) -> bool:
    return isinstance(node, str) or (isinstance(node, dict) and "other" in node)


def messages(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [m for item in node for m in messages(item)]
    if isinstance(node, dict):
        return [m for value in node.values() for m in messages(value)]
    return []


def test_every_literal_key_is_in_the_catalogue() -> None:
    pattern = re.compile(r"\b(?:t|tp)\('([a-z0-9_.]+)'")
    used = {k for text in SOURCES.values() for k in pattern.findall(text)}
    # Prefixes completed at run time from fixed lists, checked below.
    used = {k for k in used if not k.endswith(("_", "."))}
    assert len(used) > 200
    assert [k for k in sorted(used) if not is_message(lookup(k))] == []


def test_keys_built_from_fixed_lists_exist() -> None:
    learn = SOURCES[APP / "views" / "learn.js"]
    topics = re.search(r"const TOPICS = \[([^\]]+)\]", learn)
    assert topics
    for topic in re.findall(r"'(\w+)'", topics.group(1)):
        page = lookup(f"learn.topics.{topic}")
        assert isinstance(page, dict) and page["simple"] and page["detailed"], topic
        assert is_message(page["title"]) and is_message(page["blurb"]), topic
    for key in (
        [f"start.titles.{i}" for i in range(5)]
        + [
            f"nav.{n}"
            for n in ("home", "markets", "strategies", "backtests", "signals")
        ]
        + ["nav.learn", "nav.settings", "level.simple", "level.detailed"]
        + [f"settings.theme_{v}" for v in ("system", "light", "dark")]
        + [f"settings.later_{v}" for v in ("play_money", "model")]
        + [f"nav.{n}" for n in ("leaderboards", "team", "notifications", "delivery")]
        + [f"shadow.states.{k}" for k in ("queued", "running", "done", "failed")]
        + [f"shadow.origin.{k}" for k in ("enumerated", "model")]
        + [f"shadow.parts.{k}" for k in ("sizing", "timing", "selection")]
        + [
            f"health.{g}.{k}"
            for g in ("states", "line")
            for k in ("too_early", "healthy", "watch", "decayed")
        ]
        + [
            f"promotion.criteria.{k}"
            for k in (
                "enough_markets",
                "backtest_skill",
                "forward_skill",
                "no_leakage",
                "healthy",
                "mandate",
            )
        ]
        + [f"promotion.targets.{k}" for k in ("paper", "live")]
        + [
            f"jobs.kind.{k}"
            for k in (
                "backtest",
                "compile",
                "research",
                "signal_bench",
                "benchmark_freeze",
                "benchmark_score",
                "paper_cycle",
                "settle",
                "leakage",
                "shadow_import",
            )
        ]
        + [
            f"strategy.status.{k}"
            for k in ("draft", "previewed", "backtested", "paper", "retired")
        ]
        + [f"describe.example_{k}" for k in ("one", "two", "three")]
        + [f"research.example_{k}" for k in ("one", "two", "three")]
        + [f"signals.verdict.{k}" for k in ("alive", "par", "anti", "too_few")]
        + [
            f"jobs.state.{k}"
            for k in ("queued", "running", "succeeded", "failed", "dead", "cancelled")
        ]
    ):
        assert is_message(lookup(key)), key


def test_every_glossary_entry_is_complete() -> None:
    glossary = lookup("glossary")
    assert isinstance(glossary, dict)
    for key, entry in glossary.items():
        assert set(entry) == {"name", "text", "doc"}, key


def test_messages_are_safe_in_html_and_attributes() -> None:
    unsafe = [m for m in messages(CATALOGUE) if '"' in m or re.search(r"<[a-z/!]", m)]
    assert unsafe == []


def test_every_module_the_page_imports_exists() -> None:
    page = (APP.parent / "index.html").read_text()
    assert 'src="/app/main.js"' in page and 'href="/app/app.css"' in page
    for path, text in SOURCES.items():
        for target in re.findall(r"from '(\.[^']+)'", text):
            assert (path.parent / target).resolve().is_file(), (path.name, target)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_every_module_parses() -> None:
    """The page has no build step, so a syntax error reaches the browser;
    parsing every module as a module catches it here (a plain `node
    --check` reads the files as scripts and misses some)."""
    for path in sorted(APP.rglob("*.js")):
        parsed = subprocess.run(
            ["node", "--input-type=module", "--check"],
            input=path.read_text(),
            capture_output=True,
            text=True,
        )
        assert parsed.returncode == 0, f"{path.name}: {parsed.stderr[:400]}"
