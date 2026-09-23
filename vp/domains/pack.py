"""Domain packs: what a model should know about a domain, as markdown.

One file per domain in ``vp/domains/packs/`` (plan, task 56): frontmatter
(``domain``, ``title``, ``summary``, ``updated``, ``sources``) and sections
on how questions are phrased, which fields parse, which evidence exists and
what its cutoff means, base rates measured on the resolved sets, and known
pitfalls. They are written from primary sources (the venue's own events and
the resolved data) and each fact names its source or its date.

They are read with progressive disclosure: a prompt carries each pack's
one-line summary and its fields, and the rest is fetched a section at a
time when needed, so a conversation about one domain does not pay for all
of them. The platform's copies are versioned by their hash; a workspace
may keep its own edited copy (``override``), which is hashed the same way
so a run records exactly the text its model saw.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

PACKS = Path(__file__).parent / "packs"

_FRONT = re.compile(r"^---\n(?P<meta>.*?)\n---\n(?P<body>.*)$", re.S)


@dataclass(frozen=True)
class Pack:
    """One domain pack: its metadata, its markdown and the hash of the text."""

    domain: str
    meta: dict[str, str]
    body: str
    sha256: str

    @property
    def summary(self) -> str:
        """One line: the title and what the domain's markets are about."""
        return f"{self.meta.get('title', self.domain)}: {self.meta.get('summary', '')}"

    def sections(self) -> list[str]:
        """The section headings, in order."""
        return re.findall(r"^## (.+)$", self.body, re.M)

    def section(self, name: str) -> str | None:
        """One section's text without its heading, or ``None``."""
        parts = re.split(r"^## (.+)$", self.body, flags=re.M)
        for heading, text in zip(parts[1::2], parts[2::2], strict=True):
            if heading.strip().lower() == name.strip().lower():
                return text.strip()
        return None


def parse(text: str) -> Pack:
    """Read a pack from its text; raises ``ValueError`` without frontmatter."""
    m = _FRONT.match(text)
    if m is None:
        raise ValueError("a domain pack starts with a --- frontmatter block")
    meta = {}
    for line in m["meta"].splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    if "domain" not in meta:
        raise ValueError("a domain pack's frontmatter names its domain")
    return Pack(
        meta["domain"],
        meta,
        m["body"].strip() + "\n",
        hashlib.sha256(text.encode()).hexdigest(),
    )


def load(domain: str, override: str | None = None) -> Pack | None:
    """The pack for ``domain``: the workspace's ``override`` text if given,
    else the platform's copy, else ``None``."""
    if override is not None:
        return parse(override)
    path = PACKS / f"{domain}.md"
    return parse(path.read_text()) if path.exists() else None
