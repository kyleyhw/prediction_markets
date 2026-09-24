"""The site's pages, each from a source in the repository (docs/site.md § 1).

Nothing here is written for the site alone: a page is a markdown file under
`docs/`, a report, the README, or markdown generated from a manifest the
code already keeps (the CLI's parser, the OpenAPI document, the MCP tools,
the signal registry, the app's glossary and Learn pages, the plan's status
tags). Every page records where it came from.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: Docs pages by group, in reading order. A page under `docs/` missing here
#: is still published, under "More", so nothing is left out by omission.
DOC_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Concepts",
        ("scoring", "sizing", "forecasters", "data_layer", "paper_trading"),
    ),
    (
        "Using the platform",
        (
            "product",
            "interface",
            "strategies",
            "signals",
            "evidence",
            "domains",
            "portfolio",
            "shadow",
            "collaboration",
        ),
    ),
    (
        "Running it",
        ("architecture", "platform", "scaling", "runbook", "security", "venues"),
    ),
    ("About the project", ("site", "usability", "ui", "provenance", "vibe_trading")),
)
LOCALE = Path("vp/ui/static/app/locales/en.json")
MCP_SOURCE = Path("vp/platform/mcp_server.py")
_STATUS = re.compile(r"^(\d+)\.\s+\[([^\]]*)\]\s*(.*)")
_PHASE = re.compile(r"^## Phase (\d+):\s*(.*)")


@dataclass
class Page:
    """One page: its address, where it sits, its markdown and its source."""

    slug: str  # "" for home, else "docs/scoring" and the like
    title: str
    section: str
    markdown: str
    source: str  # a repository path, or what it was generated from
    verified: str  # the source's last commit date
    group: str = ""
    order: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def last_verified(root: Path, path: str) -> str:
    """The date of the last commit touching ``path``, else today."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "--", path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
    except OSError:
        out = ""
    return out or datetime.now(tz=UTC).date().isoformat()


def title_of(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def _file_page(root: Path, path: str, slug: str, section: str, **kw: Any) -> Page:
    text = (root / path).read_text()
    return Page(
        slug=slug,
        title=kw.pop("title", None) or title_of(text, slug),
        section=section,
        markdown=text,
        source=path,
        verified=last_verified(root, path),
        **kw,
    )


def home(root: Path) -> Page:
    """The README's opening, up to its first section, and where to go."""
    readme = (root / "README.md").read_text()
    opening = readme.split("\n## ", 1)[0]
    body = opening.replace("# vibe-predict", "# vibe-predict", 1) + (
        "\n\nIt is a tool for building and testing strategies, with paper money "
        "first; it is not advice, and live trading is built last, behind an "
        "agreed security design ([Security](docs/security.md)).\n\n"
        "## Where to go\n\n"
        "- [Tutorials](docs/tutorials/index.md): a week with the app, for "
        "someone new to all of it.\n"
        "- [Overview](README.md): what exists today and how to run it.\n"
        "- [Docs](docs/index.md): concepts, the platform, running it.\n"
        "- [Learn](learn/index.md): the app's plain-language pages.\n"
        "- [Research Lab](docs/lab/index.md): what the platform has measured, "
        "each number with the command that reproduces it.\n"
        "- [Signals](signals/index.md): the library, each signal's method and "
        "references.\n"
        "- [Reference](reference/index.md): the command line, the web API, the "
        "tools for AI assistants, the glossary.\n"
        "- [Reports](reports/index.md): what each phase built and measured.\n"
        "- [Roadmap](roadmap/index.md): the plan's status, task by task.\n"
    )
    return Page(
        "", "vibe-predict", "Home", body, "README.md", last_verified(root, "README.md")
    )


def docs(root: Path) -> list[Page]:
    pages = [_file_page(root, "docs/index.md", "docs", "Docs", title="Docs")]
    grouped = {name: g for g, names in DOC_GROUPS for name in names}
    order = {name: i for i, name in enumerate(n for _, ns in DOC_GROUPS for n in ns)}
    for path in sorted((root / "docs").glob("*.md")):
        name = path.stem
        if name == "index":
            continue
        pages.append(
            _file_page(
                root,
                f"docs/{name}.md",
                f"docs/{name}",
                "Docs",
                group=grouped.get(name, "More"),
                order=order.get(name, 1000),
            )
        )
    pages.append(
        _file_page(root, "README.md", "overview", "Docs", title="Overview", order=-1)
    )
    for path, slug in (
        ("CONTRIBUTING.md", "contributing"),
        ("SECURITY.md", "security-policy"),
    ):
        if (root / path).exists():
            pages.append(
                _file_page(root, path, slug, "Docs", group="Community", order=2000)
            )
    return pages


def folder(root: Path, name: str, section: str) -> list[Page]:
    """A folder of `docs/` as a section: its index first, then its pages in
    file-name order (the tutorials' days, the lab's studies)."""
    pages = []
    for i, path in enumerate(sorted((root / "docs" / name).glob("*.md"))):
        slug = name if path.stem == "index" else f"{name}/{path.stem}"
        pages.append(
            _file_page(
                root,
                f"docs/{name}/{path.name}",
                slug,
                section,
                order=-1 if path.stem == "index" else i,
            )
        )
    return sorted(pages, key=lambda p: p.order)


def reports(root: Path) -> list[Page]:
    def phase(p: Path) -> int:
        m = re.match(r"phase(\d+)_", p.name)
        return int(m.group(1)) if m else 0

    found = sorted((root / "tests/reports").glob("phase*.md"), key=phase)
    pages = [
        _file_page(root, f"tests/reports/{p.name}", f"reports/{p.stem}", "Reports")
        for p in found
    ]
    listing = "\n".join(
        f"- [{pg.title}]({pg.slug.split('/')[1]}/index.md)" for pg in pages
    )
    pages.insert(
        0,
        Page(
            "reports",
            "Reports",
            "Reports",
            "# Reports\n\nEach phase ends with a report: what was built, the tests "
            "and their runtimes, what was measured live, and what was found and "
            f"fixed.\n\n{listing}\n",
            "tests/reports/",
            last_verified(root, "tests/reports"),
        ),
    )
    return pages


def roadmap(root: Path) -> Page:
    """The plan's phases and tasks with their status tags, as a table."""
    lines = (root / "PROJECT_PLAN.md").read_text().splitlines()
    out = [
        "# Roadmap",
        "",
        "Every task of the project plan with its status as the plan records it "
        "(`PROJECT_PLAN.md`, kept current as tasks finish).",
    ]
    counts: dict[str, int] = {}
    for line in lines:
        if m := _PHASE.match(line):
            out += ["", f"## Phase {m.group(1)}: {m.group(2)}", ""]
            out += ["| Task | Status | What |", "| ---: | :--- | :--- |"]
        elif m := _STATUS.match(line):
            status = m.group(2).split()[0].rstrip(",;") if m.group(2) else "?"
            counts[status] = counts.get(status, 0) + 1
            what = m.group(3).replace("|", "\\|")
            out.append(f"| {m.group(1)} | {status} | {what} |")
    summary = ", ".join(
        f"{n} {s}" for s, n in sorted(counts.items(), key=lambda x: -x[1])
    )
    out.insert(3, f"\n{summary}.")
    return Page(
        "roadmap",
        "Roadmap",
        "Roadmap",
        "\n".join(out) + "\n",
        "PROJECT_PLAN.md",
        last_verified(root, "PROJECT_PLAN.md"),
    )


def learn(root: Path) -> list[Page]:
    """The app's Learn topics, in their plain and their detailed words."""
    catalogue = json.loads((root / LOCALE).read_text())
    topics = catalogue["learn"]["topics"]
    verified = last_verified(root, str(LOCALE))
    pages = []
    for key, t in topics.items():
        body = [f"# {t['title']}", "", f"*{t['blurb']}*", "", "## In plain words", ""]
        body += [p + "\n" for p in t.get("simple", [])]
        body += ["## In detail", ""] + [p + "\n" for p in t.get("detailed", [])]
        if t.get("doc"):
            body.append(f"More in [{t['doc']}](../../{t['doc']}).")
        if t.get("refs"):
            body += ["", "## References", ""] + [f"- {r}" for r in t["refs"]]
        pages.append(
            Page(
                f"learn/{key}",
                t["title"],
                "Learn",
                "\n".join(body) + "\n",
                f"{LOCALE} (learn.topics.{key})",
                verified,
            )
        )
    listing = "\n".join(
        f"- [{p.title}]({p.slug.split('/')[1]}/index.md)" for p in pages
    )
    pages.insert(
        0,
        Page(
            "learn",
            "Learn",
            "Learn",
            "# Learn\n\nThe pages the app shows under Learn, for someone new to "
            f"prediction markets, published here too.\n\n{listing}\n",
            str(LOCALE),
            verified,
        ),
    )
    return pages


def glossary(root: Path) -> Page:
    """One glossary for the app and the site (plan, task 124)."""
    terms = json.loads((root / LOCALE).read_text())["glossary"]
    body = [
        "# Glossary",
        "",
        "The terms the app explains in Detailed mode, from the same file.",
        "",
    ]
    for _, t in sorted(terms.items(), key=lambda kv: kv[1]["name"].lower()):
        body += [f"## {t['name']}", "", t["text"], ""]
        if t.get("doc"):
            body += [f"More in [{t['doc']}](../../{t['doc']}).", ""]
    return Page(
        "reference/glossary",
        "Glossary",
        "Reference",
        "\n".join(body),
        f"{LOCALE} (glossary)",
        last_verified(root, str(LOCALE)),
    )


def cli_reference(root: Path, parser: argparse.ArgumentParser) -> Page:
    """Every command and argument, from the parser the command line runs."""
    body = [
        "# Command line",
        "",
        "For developers and the operator; people using the app never need it. "
        "Generated from the parser `vp` itself runs (`vp/cli.py`).",
        "",
    ]

    def walk(p: argparse.ArgumentParser, name: str, depth: int) -> None:
        subs = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
        args = [
            a
            for a in p._actions
            if not isinstance(a, argparse._SubParsersAction | argparse._HelpAction)
        ]
        if depth:
            body.append(f"{'#' * min(depth + 1, 4)} `{name}`")
            body.append("")
            if p.description:
                body.extend([p.description, ""])
            if args:
                body.extend(["| Argument | Default | Help |", "| :--- | :--- | :--- |"])
                for a in args:
                    flag = ", ".join(a.option_strings) or a.dest
                    default = (
                        ""
                        if a.default in (None, argparse.SUPPRESS, False)
                        else f"`{a.default}`"
                    )
                    text = (a.help or "").replace("|", "\\|").replace("%%", "%")
                    body.append(f"| `{flag}` | {default} | {text} |")
                body.append("")
        for action in subs:
            helps = {c.dest: c.help or "" for c in action._choices_actions}
            for sub_name, sub in action.choices.items():
                if not sub.description and helps.get(sub_name):
                    sub.description = helps[sub_name]
                walk(sub, f"{name} {sub_name}".strip(), depth + 1)

    walk(parser, "vp", 0)
    return Page(
        "reference/cli",
        "Command line",
        "Reference",
        "\n".join(body) + "\n",
        "vp/cli.py (build_parser)",
        last_verified(root, "vp/cli.py"),
    )


def api_reference(root: Path, openapi: dict[str, Any]) -> Page:
    """The web API's routes from the service's own OpenAPI document."""
    body = [
        "# Web API",
        "",
        "Every route the web service answers, from its OpenAPI document. "
        "Requests carry a session cookie from the browser or an API token as "
        "`Authorization: Bearer ...`; tokens are made in Settings, read-only "
        "or read-write, and limited to 120 requests a minute. The service's "
        "own interactive reference is at `/docs` on a running instance.",
        "",
    ]
    by_tag: dict[str, list[tuple[str, str, str]]] = {}
    for path, methods in sorted(openapi.get("paths", {}).items()):
        for method, op in methods.items():
            first = path.strip("/").split("/")
            tag = first[1] if first[0] == "api" and len(first) > 1 else first[0]
            summary = (op.get("summary") or "").replace("|", "\\|")
            doc = (op.get("description") or "").split("\n\n")[0].replace("\n", " ")
            by_tag.setdefault(tag or "root", []).append(
                (method.upper(), path, doc.replace("|", "\\|") or summary)
            )
    for tag, ops in sorted(by_tag.items()):
        body += [f"## {tag}", "", "| Method | Path | What |", "| :--- | :--- | :--- |"]
        body += [f"| {m} | `{p}` | {d} |" for m, p, d in ops]
        body.append("")
    info = openapi.get("info", {})
    body.append(
        f"OpenAPI {openapi.get('openapi', '')}, "
        f"service version {info.get('version', '')}."
    )
    return Page(
        "reference/api",
        "Web API",
        "Reference",
        "\n".join(body) + "\n",
        "the service's OpenAPI document (vp/platform/web.py)",
        last_verified(root, "vp/platform/web.py"),
    )


def mcp_reference(root: Path, allowed: tuple[str, ...]) -> Page:
    """The read-only tools for AI assistants, read from the server's source."""
    tree = ast.parse((root / MCP_SOURCE).read_text())
    body = [
        "# Tools for AI assistants (MCP)",
        "",
        "A read-only MCP server at `/mcp` over streamable HTTP. An assistant "
        "presents one of its person's API tokens; every tool reads only that "
        "person's workspace. No tool can place, sign or send anything, and the "
        "list below is the whole list.",
        "",
        "| Tool | Arguments | What it returns |",
        "| :--- | :--- | :--- |",
    ]
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in allowed:
            args = [a.arg for a in node.args.args if a.arg != "ctx"]
            doc = (ast.get_docstring(node) or "").split("\n\n")[0].replace("\n", " ")
            body.append(f"| `{node.name}` | {', '.join(args)} | {doc} |")
    return Page(
        "reference/mcp",
        "Tools for AI assistants",
        "Reference",
        "\n".join(body) + "\n",
        str(MCP_SOURCE),
        last_verified(root, str(MCP_SOURCE)),
    )


def reference_index(root: Path, pages: list[Page]) -> Page:
    listing = "\n".join(
        f"- [{p.title}]({p.slug.split('/')[1]}/index.md)" for p in pages
    )
    return Page(
        "reference",
        "Reference",
        "Reference",
        f"# Reference\n\n{listing}\n",
        "generated",
        datetime.now(tz=UTC).date().isoformat(),
    )


def signals(root: Path, manifest: list[dict[str, Any]]) -> list[Page]:
    """One page per signal from the registry's manifest, and the list."""
    verified = last_verified(root, "vp/signals")
    pages = []
    for s in manifest:
        body = [
            f"# {s['title']}",
            "",
            f"`{s['id']}`: a signal in the library (`docs/signals.md`).",
            "",
            "| | |",
            "| :--- | :--- |",
            f"| Domains | {', '.join(s['domains']) or 'any'} |",
            f"| Market kinds | {', '.join(s['kinds']) or 'any'} |",
            f"| Reads | {', '.join(s['accessors'])} |",
            f"| Cutoff | {s['cutoff']} |",
            f"| Warm-up | {s['warmup']} |",
            f"| Sees the market price | {'yes' if s['uses_price'] else 'no'} |",
            f"| Licence | {s['licence']} |",
            f"| Module hash | `{s['module_sha256'][:16]}` |",
            "",
            "## References",
            "",
        ]
        body += [f"- {r}" for r in s["references"]]
        body += [
            "",
            "## How it has done",
            "",
            "Each signal is benched against the market on every domain it "
            "covers (`vp signals bench`); the results and what they mean are in "
            "the [Phase 16 report](../../tests/reports/phase16_signals.md) and, "
            "for weather, the [Phase 17 report]"
            "(../../tests/reports/phase17_evidence.md).",
        ]
        pages.append(
            Page(
                f"signals/{s['id']}",
                s["title"],
                "Signals",
                "\n".join(body) + "\n",
                "the signal registry's manifest (vp/signals/registry.py)",
                verified,
            )
        )
    rows = "\n".join(
        f"| [{s['title']}]({s['id']}/index.md) | `{s['id']}` | "
        f"{', '.join(s['kinds']) or 'any'} | {'yes' if s['uses_price'] else 'no'} |"
        for s in manifest
    )
    pages.insert(
        0,
        Page(
            "signals",
            "Signals",
            "Signals",
            "# Signals\n\nThe library: each signal is a pure function of the "
            "evidence before a cutoff, with metadata, references and a licence "
            "note, checked by `vp signals check` and benched against the market. "
            "The contract and the gates are in [the signals page]"
            "(../docs/signals.md).\n\n"
            "| Signal | Id | Kinds | Sees the price |\n| :--- | :--- | :--- | :--- |\n"
            f"{rows}\n",
            "the signal registry's manifest (vp/signals/registry.py)",
            verified,
        ),
    )
    return pages
