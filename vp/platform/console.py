"""`vp jobs` and `vp admin`: the operator's commands, printed for a terminal."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from vp.platform import audit, ops
from vp.platform.run import owner_connection


def _row(values: list[Any], widths: list[int]) -> str:
    return "  ".join(
        str(v if v is not None else "-")[:w].ljust(w)
        for v, w in zip(values, widths, strict=True)
    )


def _when(value: datetime | None) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S") if value else "-"


def _month(text: str) -> date:
    return datetime.strptime(text, "%Y-%m").replace(tzinfo=UTC).date()


def operator_command(args: argparse.Namespace) -> None:
    """Run one operator command as the owner."""
    with owner_connection() as conn:
        if args.command == "jobs":
            _jobs(conn, args)
        else:
            _admin(conn, args)


def _jobs(conn: Any, args: argparse.Namespace) -> None:
    command = args.jobs_command
    if command == "list":
        widths = [36, 12, 10, 36, 3, 19, 40]
        print(
            _row(
                ["id", "kind", "state", "workspace", "try", "created", "error"], widths
            )
        )
        for j in ops.list_jobs(
            conn, state=args.state, kind=args.kind, limit=args.limit
        ):
            print(
                _row(
                    [
                        j["id"],
                        j["kind"],
                        j["state"],
                        j["workspace_id"] or "platform",
                        j["attempts"],
                        _when(j["created_at"]),
                        j["error"],
                    ],
                    widths,
                )
            )
    elif command == "show":
        job = ops.show_job(conn, UUID(args.job_id))
        if job is None:
            raise SystemExit("no such job")
        for key, value in job.items():
            print(f"{key:>12}: {value}")
    elif command == "retry":
        print(
            "queued again"
            if ops.retry_job(conn, UUID(args.job_id))
            else "not retryable"
        )
    elif command in ("drain", "undrain"):
        ops.set_drain(conn, args.kind, command == "drain")
        print(f"{args.kind}: {'drained' if command == 'drain' else 'claimed again'}")
    elif command == "stats":
        for kind, state, count, age in ops.queue_depth(conn):
            print(f"{kind:>12} {state:>9} {count:>6}  oldest {age or 0:,.0f} s")


def _admin(conn: Any, args: argparse.Namespace) -> None:
    command = args.admin_command
    if command == "halt":
        print(f"platform halted ({ops.halt(conn, args.reason)})")
    elif command == "resume":
        print(f"cleared {ops.resume(conn)} platform halt(s)")
    elif command == "pause":
        print(f"workspace paused ({ops.halt(conn, args.reason, UUID(args.workspace))})")
    elif command == "unpause":
        print(f"cleared {ops.resume(conn, UUID(args.workspace))} pause(s)")
    elif command == "halts":
        for h in ops.active_halts(conn):
            workspace = str(h["workspace_id"] or "")
            print(
                f"{h['scope']:>9} {workspace:36} {_when(h['set_at'])} "
                f"{h['set_by']}: {h['reason']}"
            )
    elif command == "budget":
        try:
            usd = Decimal(args.usd)
        except InvalidOperation:
            raise SystemExit("the budget is a number of dollars") from None
        ops.set_budget(conn, UUID(args.workspace), usd)
        print(f"monthly model budget set to ${usd}")
    elif command == "costs":
        month = _month(args.month) if args.month else None
        total = Decimal(0)
        for ws, forecaster, domain, model, usd in ops.costs(conn, month):
            name, where = forecaster or "-", domain or "-"
            print(f"{ws}  {name:>12} {where:>8} {model or '-':>20} ${usd:,.4f}")
            total += usd
        print(f"total ${total:,.4f}")
    elif command == "refresh":
        ids = ops.refresh(conn, args.domain, tuple(args.what))
        print(f"queued {len(ids)} job(s): {', '.join(map(str, ids))}")
    elif command == "archive":
        _archive(conn, _month(args.before))
    elif command == "audit":
        broken = audit.verify(conn)
        entries = audit.entries(conn)
        print(
            "audit chain: "
            + ("verified" if broken is None else f"broken at {broken}")
            + f", {len(entries)} entries"
        )
        for e in entries[-10:]:
            who = e["data"].get("principal", {}).get("subject")
            print(f"  #{e['seq']} {e['at']} {e['kind']} by {who}")


def _archive(conn: Any, before: date) -> None:
    from vp.platform.archive import TABLES, archive_month
    from vp.platform.config import load_settings
    from vp.platform.storage import open_store

    store = open_store(load_settings())
    rows = conn.execute(
        "select distinct substring(c.relname from '_(\\d{6})$') from pg_inherits i "
        "join pg_class c on c.oid = i.inhrelid join pg_class p on p.oid = i.inhparent "
        "where p.relname = any(%s)",
        (list(TABLES),),
    ).fetchall()
    months = sorted(
        m for (s,) in rows if s and (m := datetime.strptime(s, "%Y%m").date()) < before
    )
    for month in months:
        for table in TABLES:
            moved = archive_month(conn, store, table, month)
            if moved:
                print(f"{table} {month:%Y-%m}: {moved} rows archived")
    audit.append(
        conn,
        "archive",
        {"before": before.isoformat(), "months": [str(m) for m in months]},
        ops.operator(),
    )
