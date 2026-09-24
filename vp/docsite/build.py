"""Render the pages to a static site and check it (docs/site.md § 3).

Markdown becomes HTML with markdown-it, and TeX becomes MathML that the
browser draws without a script. A link to another source in the
repository becomes a relative link to that source's page, and a link to
code becomes a link to the file on GitHub. Every page is written twice:
as `index.html` and as the markdown it came from (`index.md`), which
`llms.txt` lists for agents. `check` fails the build on a broken link or
anchor, a page missing from the navigation, or a documented `vp` command
the parser no longer accepts.
"""

from __future__ import annotations

import argparse
import contextlib
import html
import io
import json
import posixpath
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from latex2mathml.converter import convert as to_mathml
from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin

from vp.docsite.pages import Page

REPO_URL = "https://github.com/kyleyhw/prediction_markets"
STATIC = Path(__file__).parent / "static"
FONTS = Path(__file__).resolve().parent.parent / "ui" / "static" / "fonts"
SECTIONS = ("Home", "Docs", "Learn", "Signals", "Reference", "Reports", "Roadmap")
_HREF = re.compile(r'(?:href|src)="([^"]+)"')
_ID = re.compile(r'\bid="([^"]+)"')
_TAGS = re.compile(r"<[^>]+>")
_FENCE_LANGS = {"bash", "sh", "shell", "console"}


def _math(content: str, options: dict[str, Any]) -> str:
    try:
        return to_mathml(
            content, display="block" if options.get("display_mode") else "inline"
        )
    except Exception:  # noqa: BLE001 - an unparsable formula shows as its source
        return f"<code>{html.escape(content)}</code>"


def markdown() -> MarkdownIt:
    md = MarkdownIt("commonmark", {"html": True, "typographer": False}).enable(
        ["table", "strikethrough"]
    )
    # `$5 a month` is money, not math: a formula never starts with a digit
    # or a space here.
    dollarmath_plugin(md, allow_space=False, allow_digits=False, renderer=_math)
    anchors_plugin(md, min_level=2, max_level=4, permalink=True, permalinkSymbol="#")
    return md


@dataclass
class Rendered:
    page: Page
    html: str
    toc: list[tuple[int, str, str]]
    text: str
    commands: list[tuple[bool, str]]  # (whole command, text)
    sections: list[tuple[str, str, str]]  # (anchor, heading, text) for search


class Site:
    def __init__(self, root: Path, pages: list[Page]) -> None:
        self.root = root
        self.pages = pages
        self.md = markdown()
        # A page is found by its source file, or by its own address.
        self.by_key: dict[str, Page] = {}
        for p in pages:
            self.by_key[f"{p.slug}/index.md" if p.slug else "index.md"] = p
            # Home quotes the README; the README's own page is the overview.
            if p.slug and (root / p.source).is_file():
                self.by_key.setdefault(p.source, p)

    # ------------------------------------------------------------ addresses

    @staticmethod
    def url(slug: str) -> str:
        return f"{slug}/" if slug else ""

    @staticmethod
    def rel(from_slug: str, to_url: str) -> str:
        """A link from one page's directory to a path under the site root.
        Every page is a directory, so the way up is one step a segment."""
        up = "../" * (from_slug.count("/") + 1) if from_slug else ""
        return (up + to_url) or "./"

    def base(self, page: Page) -> str:
        if (self.root / page.source).is_file():
            return page.source
        return f"{page.slug}/index.md" if page.slug else "index.md"

    def resolve(self, page: Page, href: str) -> str:
        if re.match(r"^[a-z]+:", href) or href.startswith("#"):
            return href
        path, _, fragment = href.partition("#")
        target = posixpath.normpath(
            posixpath.join(posixpath.dirname(self.base(page)), path)
        )
        frag = f"#{fragment}" if fragment else ""
        if target in self.by_key:
            return self.rel(page.slug, self.url(self.by_key[target].slug)) + frag
        if target.startswith("..") or not (self.root / target).exists():
            return href
        kind = "tree" if (self.root / target).is_dir() else "blob"
        return f"{REPO_URL}/{kind}/master/{target}{frag}"

    # ------------------------------------------------------------ rendering

    def render(self, page: Page) -> Rendered:
        env: dict[str, Any] = {}
        tokens = self.md.parse(page.markdown, env)
        toc, commands = [], []
        sections: list[tuple[str, str, list[str]]] = [("", "", [])]
        for i, tok in enumerate(tokens):
            if tok.type == "heading_open" and tok.tag in ("h2", "h3"):
                inline = tokens[i + 1]
                toc.append(
                    (int(tok.tag[1]), str(tok.attrs.get("id", "")), inline.content)
                )
                sections.append((str(tok.attrs.get("id", "")), inline.content, []))
            elif tok.type in ("inline", "fence", "code_block") and not (
                i and tokens[i - 1].type == "heading_open"
            ):
                sections[-1][2].append(tok.content)
            if tok.type == "fence" and tok.info.split(" ")[0] in _FENCE_LANGS:
                commands += [(True, c) for c in _commands(tok.content)]
            for t in [tok, *(tok.children or [])]:
                if t.type == "code_inline":
                    commands += [(False, c) for c in _commands(t.content)]
                if t.type == "link_open" and "href" in t.attrs:
                    t.attrs["href"] = self.resolve(page, str(t.attrs["href"]))
        body = self.md.renderer.render(tokens, self.md.options, env)
        # Wide tables and formulas scroll inside themselves, so a keyboard
        # must be able to reach them (axe: scrollable-region-focusable).
        body = (
            body.replace("<table>", '<div class="table" tabindex="0"><table>')
            .replace("</table>", "</table></div>")
            .replace(
                '<div class="math block">',
                '<div class="math block" tabindex="0" role="group" '
                'aria-label="Formula">',
            )
        )
        text = html.unescape(_TAGS.sub(" ", body))
        return Rendered(
            page,
            body,
            toc,
            re.sub(r"\s+", " ", text),
            commands,
            [(a, h, re.sub(r"\s+", " ", " ".join(t))) for a, h, t in sections],
        )

    def nav(self, current: Page) -> str:
        parts = []
        for section in SECTIONS:
            members = [p for p in self.pages if p.section == section]
            if not members:
                continue
            head = members[0]
            cls = ' aria-current="page"' if head is current else ""
            parts.append(
                f'<li><a href="{self.rel(current.slug, self.url(head.slug))}"{cls}>'
                f"{html.escape(section)}</a>"
            )
            if current.section == section and len(members) > 1:
                parts.append(self._subnav(current, members[1:]))
            parts.append("</li>")
        return f'<ul class="nav">{"".join(parts)}</ul>'

    def _subnav(self, current: Page, members: list[Page]) -> str:
        groups: dict[str, list[Page]] = {}
        for p in sorted(members, key=lambda p: (p.order, p.title)):
            groups.setdefault(p.group, []).append(p)
        out = []
        for group, ps in groups.items():
            if group:
                out.append(f'<li class="group">{html.escape(group)}</li>')
            for p in ps:
                cls = ' aria-current="page"' if p is current else ""
                href = self.rel(current.slug, self.url(p.slug))
                out.append(f'<li><a href="{href}"{cls}>{html.escape(p.title)}</a></li>')
        return f'<ul class="subnav">{"".join(out)}</ul>'

    def document(self, r: Rendered) -> str:
        page = r.page
        to_root = self.rel(page.slug, "")
        toc = "".join(
            f'<li class="l{lvl}"><a href="#{html.escape(i)}">{html.escape(t)}</a></li>'
            for lvl, i, t in r.toc
            if i
        )
        aside = (
            '<nav class="toc" aria-label="On this page"><p>On this page</p>'
            f"<ul>{toc}</ul></nav>"
            if len(r.toc) > 2
            else ""
        )
        source = (
            f'<a href="{REPO_URL}/blob/master/{page.source}">'
            f"{html.escape(page.source)}</a>"
            if (self.root / page.source).is_file()
            else html.escape(page.source)
        )
        title = "vibe-predict" if not page.slug else f"{page.title} · vibe-predict"
        return f"""<!doctype html>
<html lang="en" data-root="{to_root}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(_description(r.text))}">
<link rel="stylesheet" href="{to_root}site.css">
<link rel="alternate" type="text/markdown" href="index.md">
<script src="{to_root}site.js" defer></script>
</head>
<body>
<a class="skip" href="#content">Skip to the content</a>
<header class="bar">
<a class="brand" href="{to_root}">vibe-predict</a>
<form class="search" role="search" action="{to_root}search/">
<label for="q" class="sr-only">Search the documentation</label>
<input id="q" name="q" type="search" placeholder="Search" autocomplete="off">
<ul id="results" class="results" hidden></ul>
</form>
<button id="theme" class="theme" type="button"
 aria-label="Switch between light and dark">◐</button>
</header>
<div class="layout">
<nav class="side" aria-label="Sections">{self.nav(page)}</nav>
<main id="content">
<article>{r.html}</article>
<footer class="meta">Source: {source} · last verified {page.verified} ·
<a href="index.md">this page as markdown</a></footer>
</main>
{aside}
</div>
</body>
</html>
"""


def _description(text: str) -> str:
    words = text.split(" ")
    return " ".join(words[:40]).strip()


def _commands(block: str) -> list[str]:
    out = []
    for line in block.splitlines():
        line = line.strip().lstrip("$ ").split(" #")[0].strip()
        for prefix in ("uv run vp ", "vp "):
            if line.startswith(prefix):
                out.append(line[len(prefix) :])
    return out


# ------------------------------------------------------------------ building


def build(
    root: Path, out: Path, pages: list[Page], parser: argparse.ArgumentParser
) -> dict[str, Any]:
    """Write the site to ``out``; returns counts and the problems found."""
    site = Site(root, pages)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copy(STATIC / "site.css", out / "site.css")
    shutil.copy(STATIC / "site.js", out / "site.js")
    (out / "fonts").mkdir()
    for font in FONTS.glob("*.woff2"):
        shutil.copy(font, out / "fonts" / font.name)
    rendered = [site.render(p) for p in pages]
    index = []
    for r in rendered:
        folder = out / r.page.slug if r.page.slug else out
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(site.document(r))
        (folder / "index.md").write_text(r.page.markdown)
        # One entry a section, so a long page is searched whole and a result
        # opens at the part that matched.
        for anchor, heading, text in r.sections:
            if not (anchor or text):
                continue
            index.append(
                {
                    "u": site.url(r.page.slug) + (f"#{anchor}" if anchor else ""),
                    "t": r.page.title,
                    "s": r.page.section,
                    "h": heading,
                    "x": text[:3000],
                }
            )
    (out / "search.json").write_text(json.dumps(index, separators=(",", ":")))
    search = Page(
        "search",
        "Search",
        "Search",
        "# Search\n\nResults for your search appear here.\n",
        "generated",
        "",
    )
    (out / "search").mkdir(exist_ok=True)
    (out / "search" / "index.html").write_text(
        site.document(
            Rendered(
                search, '<h1>Search</h1><ul id="page-results"></ul>', [], "", [], []
            )
        )
    )
    (out / "search" / "index.md").write_text(search.markdown)
    (out / "llms.txt").write_text(_llms(site, rendered))
    problems = check(out) + _check_commands(parser, rendered) + _check_nav(root, pages)
    return {
        "pages": len(rendered),
        "bytes": sum(f.stat().st_size for f in out.rglob("*") if f.is_file()),
        "problems": problems,
    }


def _llms(site: Site, rendered: list[Rendered]) -> str:
    lines = [
        "# vibe-predict",
        "",
        "> A platform for building forecasting strategies for binary prediction-"
        "market contracts, scoring them against the market's own price, and "
        "paper trading them. Every page below is also served as markdown.",
        "",
    ]
    for section in SECTIONS:
        members = [r for r in rendered if r.page.section == section]
        if members:
            lines += [f"## {section}", ""]
            lines += [
                f"- [{r.page.title}]({site.url(r.page.slug)}index.md): "
                f"{_description(r.text)[:160]}"
                for r in members
            ]
            lines.append("")
    return "\n".join(lines)


def check(out: Path) -> list[str]:
    """Every internal link and anchor resolves."""
    problems = []
    ids: dict[Path, set[str]] = {}
    files = sorted(out.rglob("*.html"))
    for f in files:
        ids[f.resolve()] = set(_ID.findall(f.read_text()))
    for f in files:
        for href in _HREF.findall(f.read_text()):
            if re.match(r"^[a-z]+:", href) or href.startswith("//"):
                continue
            path, _, fragment = html.unescape(href).partition("#")
            target = (f.parent / path).resolve() if path else f.resolve()
            if target.is_dir():
                target = target / "index.html"
            if not target.exists():
                problems.append(f"{f.relative_to(out)}: broken link {href}")
            elif (
                fragment
                and target.suffix == ".html"
                and fragment not in ids.get(target, set())
            ):
                problems.append(
                    f"{f.relative_to(out)}: no anchor #{fragment} in {href}"
                )
    return problems


def _check_commands(
    parser: argparse.ArgumentParser, rendered: list[Rendered]
) -> list[str]:
    """A documented `vp` command the parser no longer accepts (task 124).

    A command in a code block is meant to be run, so it must parse whole. A
    command named in the text (`vp backtest`) often leaves its arguments
    out, so only its command names and flags must exist.
    """
    problems = []
    for r in rendered:
        for whole, cmd in r.commands:
            if re.search(r"[<>\[\]{}…|$]|\.\.\.|\b[A-Z]\b", cmd) or cmd[:1].isdigit():
                continue  # a template or a version, not a command
            if "-h" in cmd.split() or "--help" in cmd:
                continue
            bad = _parses(parser, cmd) if whole else _names_exist(parser, cmd)
            if bad:
                problems.append(f"{r.page.source}: `vp {cmd}` {bad}")
    return problems


def _parses(parser: argparse.ArgumentParser, cmd: str) -> str | None:
    try:
        with (
            contextlib.redirect_stderr(io.StringIO()),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            parser.parse_args(shlex.split(cmd))
    except SystemExit as done:
        return None if done.code in (0, None) else "no longer parses"
    except ValueError:
        return "no longer parses"
    return None


def _names_exist(parser: argparse.ArgumentParser, cmd: str) -> str | None:
    p = parser
    for word in shlex.split(cmd):
        subs = [a for a in p._actions if isinstance(a, argparse._SubParsersAction)]
        if word.startswith("-"):
            flags = {o for a in p._actions for o in a.option_strings}
            if word.split("=")[0] not in flags:
                return f"has no option {word.split('=')[0]}"
        elif subs and word in subs[0].choices:
            p = subs[0].choices[word]
        elif subs:
            return f"has no command {word}"
    return None


def _check_nav(root: Path, pages: list[Page]) -> list[str]:
    published = {p.source for p in pages}
    return [
        f"docs/{p.name} is not published"
        for p in sorted((root / "docs").glob("*.md"))
        if f"docs/{p.name}" not in published
    ]
