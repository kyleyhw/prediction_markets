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

from collections.abc import Iterator
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from vp.paper.ledger import ChainLedger
from vp.platform.db import tenant_session
from vp.platform.ledger import PgLedger
from vp.platform.principal import Principal
from vp.platform.storage import ObjectStore, SharedRoot
from vp.ui.server import START_CASH, DataView


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


def paper_account(pool: ConnectionPool, principal: Principal) -> dict[str, Any] | None:
    """The workspace's paper account (the first opened), or None."""
    with pool.connection() as conn, tenant_session(conn, principal):
        cur = conn.cursor(row_factory=dict_row)
        return cur.execute(
            "select id, name, domains, forecasters, initial_cash, created_at "
            "from paper_accounts order by created_at limit 1"
        ).fetchone()


class WorkspaceView(DataView):
    """The dashboard's queries for one principal's workspace."""

    def __init__(
        self,
        shared: SharedRoot,
        pool: ConnectionPool,
        principal: Principal,
        store: ObjectStore,
    ) -> None:
        super().__init__(shared.root)
        self.pool = pool
        self.principal = principal
        self.store = store
        self.account = paper_account(pool, principal)
        self._runs: list[dict[str, Any]] | None = None

    def ledger(self) -> ChainLedger:
        if self.account is None:
            return NoLedger()
        return PgLedger(self.pool, self.principal, self.account["id"], store=self.store)

    def start_cash(self) -> float:
        return float(self.account["initial_cash"]) if self.account else START_CASH

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
        return view
