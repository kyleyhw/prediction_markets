"""Archive old monthly partitions to Parquet in the object store.

Ledger entries and forecasts grow without bound, so each month is a
partition (migration 0004) and a month older than the retention window is
moved out of Postgres: its rows are written to one Parquet file under
`archive/<table>/<YYYYMM>.parquet`, read back and counted, and only then is
the partition detached and dropped. A ledger entry keeps its full JSON,
hash included, so an account's chain can still be verified end to end by
reading its archived months before its live ones (`archived_entries`).

This runs as the owner (it drops tables), from `vp admin archive`, never
from the web or a worker.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from datetime import date
from typing import Any
from uuid import UUID

import duckdb
import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
from psycopg import sql

from vp.platform.storage import ObjectStore

TABLES = ("ledger_entries", "forecasts")
# Literal column lists, one per table: text casts keep the Parquet schema
# plain, and the entry keeps its full JSON with the hash.
_LEDGER_COLUMNS = sql.SQL(
    "account_id::text, workspace_id::text, seq, at, kind, entry::text, hash"
)
_FORECAST_COLUMNS = sql.SQL(
    "id, workspace_id::text, account_id::text, job_id::text, forecaster, "
    "market_id, domain, p_hat, cutoff, cost_usd::float8, memo_key, record::text, at"
)


def archive_key(table: str, month: date) -> str:
    return f"archive/{table}/{month:%Y%m}.parquet"


def archive_month(
    conn: psycopg.Connection, store: ObjectStore, table: str, month: date
) -> int:
    """Move one month of one table to the object store; returns the rows moved.

    Raises:
        ValueError: the table is not archivable, or the month is the current
            one or later.
        RuntimeError: the file read back does not hold every row, in which
            case nothing is dropped.
    """
    if table not in TABLES:
        raise ValueError(f"{table} is not archived")
    month = month.replace(day=1)
    if month >= date.today().replace(day=1):
        raise ValueError("only months that have ended can be archived")
    partition = f"{table}_{month:%Y%m}"
    exists = conn.execute("select to_regclass(%s) is not null", (partition,)).fetchone()
    if not exists or not exists[0]:
        return 0
    cursor = conn.execute(
        sql.SQL("select {} from {}").format(
            _LEDGER_COLUMNS if table == "ledger_entries" else _FORECAST_COLUMNS,
            sql.Identifier(partition),
        )
    )
    names = [d.name for d in cursor.description or []]
    rows = cursor.fetchall()
    table_data = pa.Table.from_pylist([dict(zip(names, r, strict=True)) for r in rows])
    buffer = io.BytesIO()
    pq.write_table(table_data, buffer)
    key = archive_key(table, month)
    store.put_bytes(key, buffer.getvalue())
    stored = store.get_bytes(key)
    if stored is None or pq.read_table(io.BytesIO(stored)).num_rows != len(rows):
        raise RuntimeError(f"{key} does not hold all {len(rows)} rows; nothing dropped")
    with conn.transaction():
        conn.execute(
            sql.SQL("alter table {} detach partition {}").format(
                sql.Identifier(table), sql.Identifier(partition)
            )
        )
        conn.execute(sql.SQL("drop table {}").format(sql.Identifier(partition)))
    return len(rows)


def archived_entries(store: ObjectStore, account_id: UUID) -> Iterator[dict[str, Any]]:
    """An account's archived ledger entries, oldest month first, in chain order."""
    for key in store.keys("archive/ledger_entries/"):
        data = store.get_bytes(key)
        if data is None:
            continue
        for (entry,) in _rows_for(data, str(account_id)):
            yield json.loads(entry)


def _rows_for(data: bytes, account_id: str) -> list[tuple[str]]:
    table = pq.read_table(io.BytesIO(data), columns=["account_id", "seq", "entry"])
    con = duckdb.connect()
    con.register("archived", table)
    return con.execute(
        "select entry from archived where account_id = ? order by seq", [account_id]
    ).fetchall()
