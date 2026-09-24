"""The Research Lab (plan, task 123; docs/site.md § 2): studies whose every
number is one command away.

A study page under `docs/lab/` shows each command in a fenced block marked
``bash lab`` and, straight after it, the command's output in a ``text``
block. `check` reruns the commands and reports every page whose output
differs; `update` rewrites the outputs. A line that changes from run to run
(a runtime, a path written) is left out of both. The data is not in the
repository, so the check runs where the data is (`vp lab check`), not in
CI.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

Runner = Callable[[list[str]], str]
_VOLATILE = re.compile(r"^(runtime:|written[: ])")
_FENCE = "```"


def normalise(output: str) -> str:
    lines = [ln.rstrip() for ln in output.splitlines() if not _VOLATILE.match(ln)]
    return "\n".join(lines).strip() + "\n"


def blocks(text: str) -> list[tuple[int, int, list[str], tuple[int, int] | None]]:
    """(start, end, commands, output span) of each ``bash lab`` block; the
    span is the line range of the ``text`` block after it, if there is one."""
    lines = text.splitlines()
    found = []
    i = 0
    while i < len(lines):
        if lines[i].strip() == f"{_FENCE}bash lab":
            j = i + 1
            while j < len(lines) and lines[j].strip() != _FENCE:
                j += 1
            commands = [ln.strip() for ln in lines[i + 1 : j] if ln.strip()]
            k = j + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            span = None
            if k < len(lines) and lines[k].strip() == f"{_FENCE}text":
                m = k + 1
                while m < len(lines) and lines[m].strip() != _FENCE:
                    m += 1
                span = (k, m)
            found.append((i, j, commands, span))
            i = j + 1
        else:
            i += 1
    return found


def _run(commands: list[str], runner: Runner) -> str:
    out = []
    for command in commands:
        words = command.split()
        if words[:1] != ["vp"]:
            raise ValueError(f"a lab command starts with vp: {command}")
        out.append(runner(words[1:]))
    return normalise("\n".join(out))


def check(page: Path, runner: Runner) -> list[str]:
    """What no longer reproduces on this page."""
    text = page.read_text()
    lines = text.splitlines()
    problems = []
    for _, _, commands, span in blocks(text):
        if span is None:
            problems.append(f"{page}: `{commands[0]}` has no recorded output")
            continue
        recorded = normalise("\n".join(lines[span[0] + 1 : span[1]]))
        if _run(commands, runner) != recorded:
            problems.append(f"{page}: `{commands[0]}` gives a different result")
    return problems


def update(page: Path, runner: Runner) -> int:
    """Rewrite each block's recorded output; returns how many changed."""
    lines = page.read_text().splitlines()
    changed = 0
    # From the last block back, so earlier line numbers stay valid.
    for _, end, commands, span in reversed(blocks("\n".join(lines))):
        fresh = [
            f"{_FENCE}text",
            *_run(commands, runner).rstrip("\n").split("\n"),
            _FENCE,
        ]
        if span is None:
            lines[end + 1 : end + 1] = ["", *fresh]
            changed += 1
        elif lines[span[0] : span[1] + 1] != fresh:
            lines[span[0] : span[1] + 1] = fresh
            changed += 1
    page.write_text("\n".join(lines) + "\n")
    return changed
