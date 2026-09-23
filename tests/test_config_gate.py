"""One module reads the environment, and this is what says so.

`vp/platform/config.py` is the single reader for the platform, so that the
whole configuration surface fits on one page and a missing setting fails at
start rather than at the request that needs it. Two engine knobs predate
the platform and are listed below: they are command-line conveniences
rather than platform settings, and they move into `config.py` when the
engine runs under the service (plan, task 32).
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "vp"
CONFIG = PACKAGE / "platform" / "config.py"

#: Engine knobs that read the environment directly, each with the marker
#: that says it is still the read this entry was granted for. Adding to
#: this list is a decision, not a formality.
#:
#: `_http.py` holds the generic reader `positive_env_float`; the variable
#: it is called with (`VP_POLYMARKET_MIN_INTERVAL`) is named by its caller
#: in `venues/polymarket.py`, which is itself no longer a reader.
#:
#: `run.py` writes `PROMETHEUS_MULTIPROC_DIR` for the web processes `vp
#: serve --workers` starts; it reads nothing, and the children read the
#: variable through `config.py` and prometheus_client.
ALLOWED = {
    PACKAGE / "venues" / "_http.py": "def positive_env_float",
    PACKAGE / "live" / "controls.py": "VP_STOP_FILE",
    PACKAGE / "platform" / "run.py": "os.environ[METRICS_DIR] = metrics",
}

_READERS = {("os", "getenv"), ("os", "environ")}


def _reads_environment(tree: ast.AST) -> bool:
    """Whether the module reaches into `os.environ` or calls `os.getenv`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if (node.value.id, node.attr) in _READERS:
                return True
    return False


def test_only_the_config_module_reads_the_environment() -> None:
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == CONFIG or path in ALLOWED:
            continue
        if _reads_environment(ast.parse(path.read_text())):
            offenders.append(str(path.relative_to(PACKAGE.parent)))
    assert offenders == [], (
        "these modules read the environment directly; route them through "
        f"vp/platform/config.py or justify them in ALLOWED: {offenders}"
    )


def test_the_config_module_does_read_it() -> None:
    """Guards against the gate passing because the reader was renamed away."""
    assert _reads_environment(ast.parse(CONFIG.read_text()))


def test_the_listed_exceptions_still_exist_and_still_read_it() -> None:
    """A stale exception is a hole; remove it when the module stops reading."""
    for path, marker in ALLOWED.items():
        assert path.exists(), f"{path} is listed as an exception but is gone"
        body = path.read_text()
        assert _reads_environment(ast.parse(body)), (
            f"{path} no longer reads the environment; drop it from ALLOWED"
        )
        assert marker in body, f"{path} no longer contains {marker!r}"
