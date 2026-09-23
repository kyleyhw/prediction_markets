"""Metrics across web processes: each process records its own, and one
scrape adds them up."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

COUNT = (
    "from vp.platform.observe import HTTP_REQUESTS; "
    "HTTP_REQUESTS.labels('/api/overview', 'GET', '200').inc()"
)
SCRAPE = "from vp.platform.observe import exposition; print(exposition().decode())"


def test_several_web_processes_are_scraped_as_one(tmp_path: Path) -> None:
    env = os.environ | {"PROMETHEUS_MULTIPROC_DIR": str(tmp_path)}
    for _ in range(2):
        subprocess.run([sys.executable, "-c", COUNT], env=env, check=True)
    out = subprocess.run(
        [sys.executable, "-c", SCRAPE], env=env, check=True, capture_output=True
    ).stdout.decode()
    line = next(ln for ln in out.splitlines() if ln.startswith("vp_http_requests_total"))
    assert line.endswith(" 2.0")
