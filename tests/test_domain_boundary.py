"""Nothing outside the domain adapters names a domain (plan, task 79;
docs/domains.md): a new domain is added in `vp/domains/` and everything
else finds it through `DOMAINS` and the domain's own properties."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from vp.domains import DOMAINS

PACKAGE = Path(__file__).resolve().parent.parent / "vp"
# The domain packs are the domains' own words; the adapters are the domains.
OWN = (PACKAGE / "domains",)


def test_no_code_outside_the_adapters_names_a_domain() -> None:
    names = set(DOMAINS)
    found = []
    for path in PACKAGE.rglob("*.py"):
        if any(path.is_relative_to(own) for own in OWN):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and node.value in names:
                found.append(f"{path.relative_to(PACKAGE)}:{node.lineno}")
    pattern = re.compile(r"""["'](%s)["']""" % "|".join(sorted(names)))
    for path in (PACKAGE / "ui" / "static").rglob("*.js"):
        for i, line in enumerate(path.read_text().splitlines(), 1):
            if pattern.search(line):
                found.append(f"{path.relative_to(PACKAGE)}:{i}")
    assert found == [], f"domain names outside vp/domains: {found}"
