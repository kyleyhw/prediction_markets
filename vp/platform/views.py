"""The dashboard's views for one workspace (plan, task 37).

`WorkspaceView` answers with exactly the JSON `vp ui` does, so the page is
the same page, but reads what belongs to the workspace from Postgres as its
principal: the paper ledger of its account (`PgLedger`), its backtest runs,
its forecasts. The shared market files (datasets, histories, snapshots)
come from the process's cache of the object store, which is the data root
the view is built over. Another workspace's rows are never read, because
every query here runs in a tenant session.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from vp.paper.ledger import ChainLedger
from vp.platform.db import tenant_session
from vp.platform.ledger import PgLedger
from vp.platform.principal import Principal
from vp.platform.sample import SampleLedger, sample_account
from vp.platform.storage import ObjectStore, SharedRoot
from vp.ui.server import START_CASH, DataView

PAPER_TTL_SECONDS = 60.0
PAPER_CACHE_SIZE = 512
_PAPER: OrderedDict[tuple[Any, int, int], tuple[float, dict[str, Any]]] = OrderedDict()
_PAPER_LOCK = threading.Lock()


class NoLedger:
    """The ledger of a workspace that has not started paper trading."""

    def append(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        raise PermissionError("no paper account in this workspace")

    def entries(self) -> Iterator[dict[str, Any]]:
        return iter(())

    def last(self) -> dict[str, Any] | None:
        return None

    def verify(self) -> int | None:
        return None


def paper_account(
    pool: ConnectionPool, principal: Principal, account_id: UUID | None = None
) -> dict[str, Any] | None:
    """A paper account of the workspace: the one named, or else the first
    opened that belongs to no strategy; None when there is none."""
    with pool.connection() as conn, tenant_session(conn, principal):
        cur = conn.cursor(row_factory=dict_row)
        if account_id is not None:
            return cur.execute(
                "select id, name, domains, forecasters, initial_cash, created_at "
                "from paper_accounts where id = %s",
                (account_id,),
            ).fetchone()
        return cur.execute(
            "select id, name, domains, forecasters, initial_cash, created_at "
            "from paper_accounts where strategy_version_id is null "
            "order by created_at limit 1"
        ).fetchone()


class WorkspaceView(DataView):
    """The dashboard's queries for one principal's workspace."""

    def __init__(
        self,
        shared: SharedRoot,
        pool: ConnectionPool,
        principal: Principal,
        store: ObjectStore,
        account_id: UUID | None = None,
    ) -> None:
        super().__init__(shared.root)
        self.pool = pool
        self.principal = principal
        self.store = store
        self.account = paper_account(pool, principal, account_id)
        # Without an account of its own, a workspace reads the sample
        # strategies' account, which the platform runs for everyone (F17).
        self.sample = sample_account(pool) if self.account is None else None
        self._runs: list[dict[str, Any]] | None = None

    def ledger(self) -> ChainLedger:
        if self.account is not None:
            return PgLedger(
                self.pool, self.principal, self.account["id"], store=self.store
            )
        if self.sample is not None:
            return SampleLedger(self.pool, self.sample["id"], self.store)
        return NoLedger()

    def paper(self, *, limit: int = 50, now: datetime | None = None) -> dict[str, Any]:
        """The paper view, computed once per ledger head and minute.

        Computing it reads, decodes and verifies the whole chain (about a
        second for 14,000 entries), and every page asks for it. The ledger
        changes only when a cycle or settlement appends, which moves the
        head, so the view is kept per account and head, and recomputed at
        most once a minute for the last-24-hours figures.
        """
        if now is not None or (self.account is None and self.sample is None):
            return super().paper(limit=limit, now=now)
        if self.account is not None:
            with self.pool.connection() as conn, tenant_session(conn, self.principal):
                row = conn.execute(
                    "select seq from ledger_heads where account_id = %s",
                    (self.account["id"],),
                ).fetchone()
            key = (self.account["id"], row[0] if row else -1, limit)
        else:
            assert self.sample is not None
            key = (self.sample["id"], self.sample["head_seq"], limit)
        with _PAPER_LOCK:
            hit = _PAPER.get(key)
        if hit is not None and time.monotonic() - hit[0] < PAPER_TTL_SECONDS:
            return hit[1]
        view = super().paper(limit=limit)
        with _PAPER_LOCK:
            _PAPER[key] = (time.monotonic(), view)
            while len(_PAPER) > PAPER_CACHE_SIZE:
                _PAPER.popitem(last=False)
        return view

    def start_cash(self) -> float:
        account = self.account or self.sample
        return float(account["initial_cash"]) if account else START_CASH

    def _all_runs(self) -> list[dict[str, Any]]:
        if self._runs is None:
            with self.pool.connection() as conn, tenant_session(conn, self.principal):
                cur = conn.cursor(row_factory=dict_row)
                self._runs = cur.execute(
                    "select id, config, results, summary, created_at from runs "
                    "where kind = 'backtest' order by created_at desc limit 200"
                ).fetchall()
        return self._runs

    def backtest_count(self, domain: str) -> int:
        return sum(1 for r in self._all_runs() if r["config"].get("domain") == domain)

    def backtests(self) -> list[dict[str, Any]]:
        return [
            {
                "run_id": str(r["id"]),
                "domain": r["config"].get("domain"),
                "stamp": r["created_at"].strftime("%Y%m%dT%H%M%SZ"),
                "results": r["results"],
                "lines": [],
                "tables": [],
                "figures": [],
            }
            for r in self._all_runs()
        ]

    def forecasts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.pool.connection() as conn, tenant_session(conn, self.principal):
            rows = conn.execute(
                "select record from forecasts order by at desc limit %s", (limit,)
            ).fetchall()
        return [r[0] for r in rows]

    def latest_forecasts(self, domain: str) -> dict[str, list[dict[str, Any]]]:
        """Each strategy's latest forecast per market in the domain, read as
        the columns the list shows rather than decoded records."""
        with self.pool.connection() as conn, tenant_session(conn, self.principal):
            rows = conn.execute(
                "select distinct on (market_id, forecaster) market_id, forecaster, "
                "p_hat, cutoff from forecasts where domain = %s "
                "order by market_id, forecaster, at desc",
                (domain,),
            ).fetchall()
        out: dict[str, list[dict[str, Any]]] = {}
        for market_id, forecaster, p_hat, cutoff in rows:
            out.setdefault(str(market_id), []).append(
                {
                    "forecaster": forecaster,
                    "p_hat": float(p_hat),
                    "cutoff": cutoff.isoformat().replace("+00:00", "Z"),
                }
            )
        return out

    def signals(self) -> dict[str, Any]:
        from vp.platform.signals import latest_bench
        from vp.signals.registry import manifest

        return {"signals": manifest(), "bench": latest_bench(self.pool)}

    def benchmark(self) -> list[dict[str, Any]]:
        from vp.platform.signals import weeks

        return weeks(self.pool)

    def overview(self) -> dict[str, Any]:
        view = super().overview()
        view.pop("root", None)
        view["account"] = (
            {
                "id": str(self.account["id"]),
                "name": self.account["name"],
                "domains": self.account["domains"],
                "forecasters": self.account["forecasters"],
            }
            if self.account
            else None
        )
        # The paper figures are the sample strategies', shared by everyone.
        view["sample"] = self.account is None
        return view
