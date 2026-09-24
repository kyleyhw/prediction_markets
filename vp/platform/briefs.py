"""Scheduled briefs (plan, task 86; docs/collaboration.md).

A brief is a template with declared, typed variables, a schedule in a
timezone and a channel. It is rendered from the workspace's own data at run
time, with "today" resolved in the brief's timezone, and it ends in a fenced
``vp-brief`` block of JSON that a watch list renders without reading the
prose. No model writes a brief. The research assistant may propose one,
which is stored disabled; only a person's confirmation on the page enables
it and creates its schedule.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.forecast.evidence import parse_time
from vp.markets.schema import BinaryMarket
from vp.platform.db import tenant_session
from vp.platform.principal import Principal
from vp.platform.teams import NotAllowed, record

BLOCK = "vp-brief"


@dataclass(frozen=True)
class Variable:
    kind: type
    default: Any
    low: float | None = None
    high: float | None = None


@dataclass(frozen=True)
class Template:
    title: str
    variables: dict[str, Variable] = field(default_factory=dict)


TEMPLATES = {
    "disagreements": Template(
        "Markets closing today where your strategies disagree with the market",
        {
            "threshold": Variable(float, 10.0, 1, 50),
            "domains": Variable(list, []),
        },
    ),
    "settlements": Template(
        "Settlements in your paper accounts",
        {"days": Variable(int, 1, 1, 14)},
    ),
    "weekly": Template("Weekly P&L and skill against the market"),
}


def check_variables(template: str, given: dict[str, Any]) -> dict[str, Any]:
    """The template's variables with defaults filled; undeclared ones refused."""
    if template not in TEMPLATES:
        raise ValueError(f"a brief is one of {', '.join(TEMPLATES)}")
    declared = TEMPLATES[template].variables
    unknown = set(given) - set(declared)
    if unknown:
        raise ValueError(f"{template} has no variable {', '.join(sorted(unknown))}")
    out = {}
    for name, var in declared.items():
        value = given.get(name, var.default)
        if not isinstance(value, var.kind) or isinstance(value, bool):
            if (
                var.kind is float
                and isinstance(value, int)
                and not isinstance(value, bool)
            ):
                value = float(value)
            else:
                raise ValueError(f"{name} must be a {var.kind.__name__}")
        if var.low is not None and not var.low <= value <= (var.high or value):
            raise ValueError(f"{name} must be between {var.low:g} and {var.high:g}")
        out[name] = value
    return out


def check_schedule(cron: str, timezone: str) -> None:
    from croniter import croniter

    try:
        ZoneInfo(timezone)
    except ValueError, KeyError:
        raise ValueError(f"not a time zone: {timezone}") from None
    if not croniter.is_valid(cron):
        raise ValueError("that is not a five-field schedule")


# ------------------------------------------------------------------ render


def _block(template: str, rows: list[dict[str, Any]], today: date) -> str:
    body = {"template": template, "date": today.isoformat(), "rows": rows}
    return f"```{BLOCK}\n{json.dumps(body, sort_keys=True, default=str)}\n```"


def disagreements(
    conn: psycopg.Connection,
    variables: dict[str, Any],
    today: date,
    zone: ZoneInfo,
    open_markets: dict[str, BinaryMarket],
) -> list[dict[str, Any]]:
    """Each market ending today (in the zone) whose newest forecast by one
    of the workspace's forecasters is more than `threshold` points from its
    price now."""
    rows = conn.execute(
        "select distinct on (forecaster, market_id) forecaster, market_id, domain, "
        "p_hat from forecasts where at > now() - interval '2 days' "
        "and market_id is not null order by forecaster, market_id, at desc"
    ).fetchall()
    out = []
    domains = set(variables["domains"])
    for forecaster, market_id, domain, p in rows:
        market = open_markets.get(market_id)
        if (
            market is None
            or market.p_yes is None
            or (domains and domain not in domains)
        ):
            continue
        end = parse_time(market.end_date)
        if end is None or end.astimezone(zone).date() != today:
            continue
        gap = 100 * (p - market.p_yes)
        if abs(gap) > variables["threshold"]:
            out.append(
                {
                    "market_id": market_id,
                    "domain": domain,
                    "question": market.question,
                    "forecaster": forecaster,
                    "forecast": round(p, 3),
                    "price": round(market.p_yes, 3),
                    "points": round(gap, 1),
                    "ends": end.isoformat(),
                }
            )
    return sorted(out, key=lambda r: -abs(r["points"]))


def settlements(conn: psycopg.Connection, variables: dict[str, Any]) -> list[dict]:
    rows = conn.execute(
        "select a.name, s.at, s.entry -> 'data', "
        "(select o.entry -> 'data' ->> 'question' from ledger_entries o "
        " where o.account_id = s.account_id and o.kind = 'order' "
        " and o.entry -> 'data' ->> 'market_id' = s.entry -> 'data' ->> 'market_id' "
        " order by o.seq desc limit 1) "
        "from ledger_entries s join paper_accounts a on a.id = s.account_id "
        "where s.kind = 'settlement' and s.at > now() - %s order by s.at",
        (timedelta(days=variables["days"]),),
    ).fetchall()
    return [
        {
            "account": name,
            "at": at.isoformat(),
            "market_id": data.get("market_id"),
            "question": question,
            "won": data.get("label") == 1,
            "pnl": round(float(data.get("pnl") or 0), 2),
        }
        for name, at, data, question in rows
    ]


def weekly(conn: psycopg.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "select a.name, s.entry -> 'data' from ledger_entries s "
        "join paper_accounts a on a.id = s.account_id "
        "where s.kind = 'settlement' and s.at > now() - interval '7 days'"
    ).fetchall()
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for name, data in rows:
        by[name].append(data)
    out = []
    for name, data in sorted(by.items()):
        scored = [d for d in data if d.get("brier_market") is not None]
        brier = sum(d["brier"] for d in scored) / len(scored) if scored else None
        market = (
            sum(d["brier_market"] for d in scored) / len(scored) if scored else None
        )
        out.append(
            {
                "account": name,
                "settled": len(data),
                "pnl": round(sum(float(d.get("pnl") or 0) for d in data), 2),
                "skill": round(1 - brier / market, 4)
                if brier is not None and market
                else None,
            }
        )
    return out


def render(
    conn: psycopg.Connection,
    template: str,
    variables: dict[str, Any],
    timezone: str,
    open_markets: dict[str, BinaryMarket],
    now: datetime | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """The brief's text, ending in its block, and its rows."""
    zone = ZoneInfo(timezone)
    today = (now or datetime.now(tz=UTC)).astimezone(zone).date()
    title = TEMPLATES[template].title
    if template == "disagreements":
        rows = disagreements(conn, variables, today, zone, open_markets)
        lines = [
            f"- {r['question']} ({r['forecaster']}: {r['forecast']:.0%} against "
            f"{r['price']:.0%}, {r['points']:+.0f} points)"
            for r in rows
        ]
    elif template == "settlements":
        rows = settlements(conn, variables)
        lines = [
            f"- {r['question'] or r['market_id']}: {'won' if r['won'] else 'lost'}, "
            f"{r['pnl']:+.2f} USD ({r['account']})"
            for r in rows
        ]
    else:
        rows = weekly(conn)
        lines = [
            f"- {r['account']}: {r['settled']} settled, {r['pnl']:+.2f} USD"
            + (f", skill {r['skill']:+.3f}" if r["skill"] is not None else "")
            for r in rows
        ]
    body = "\n".join(lines) if lines else "Nothing to report."
    text = (
        f"{title} ({today.isoformat()}, {timezone})\n\n{body}\n\n"
        "Paper trading uses play money.\n\n" + _block(template, rows, today)
    )
    return text, rows


def parse_block(text: str) -> dict[str, Any] | None:
    """The machine-readable block at the end of a brief, for the watch list."""
    start = text.rfind(f"```{BLOCK}\n")
    if start < 0:
        return None
    end = text.find("\n```", start + len(BLOCK) + 4)
    return json.loads(text[start + len(BLOCK) + 4 : end]) if end > 0 else None


# ------------------------------------------------------------------ store


def propose(
    pool: ConnectionPool,
    principal: Principal,
    template: str,
    variables: dict[str, Any],
    cron: str,
    timezone: str,
    channel: UUID | None,
    proposed_by: str = "person",
) -> str:
    """Store a brief, disabled; it runs only once a person confirms it."""
    if not principal.may_write:
        raise NotAllowed("viewers cannot schedule briefs")
    clean = check_variables(template, variables)
    check_schedule(cron, timezone)
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "insert into briefs (template, variables, cron, timezone, channel_id, "
            "proposed_by) values (%s, %s, %s, %s, %s, %s) returning id",
            (template, Jsonb(clean), cron, timezone, channel, proposed_by),
        ).fetchone()
        assert row is not None
        record(conn, "brief_proposed", "brief", row[0], {"by": proposed_by})
    return str(row[0])


def confirm(pool: ConnectionPool, principal: Principal, brief: UUID) -> None:
    """Enable a brief and create its schedule; a human surface only."""
    from vp.platform.jobs import next_fire

    if not principal.may_write:
        raise NotAllowed("viewers cannot schedule briefs")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update briefs set enabled = true, confirmed_by = %s, confirmed_at = now() "
            "where id = %s and not enabled returning cron, timezone",
            (principal.user_id, brief),
        ).fetchone()
        if row is None:
            raise LookupError("no such brief waiting for confirmation")
        cron, timezone = row
        conn.execute(
            "insert into schedules (workspace_id, created_by, name, kind, payload, "
            "cron, "
            "timezone, next_run_at) values (%s, %s, %s, 'brief', %s, %s, %s, %s) "
            "on conflict do nothing",
            (
                principal.workspace,
                principal.user_id,
                f"brief {brief}",
                Jsonb({"brief_id": str(brief)}),
                cron,
                timezone,
                next_fire(cron, timezone, datetime.now(tz=UTC)),
            ),
        )
        record(conn, "brief_confirmed", "brief", brief)


def stop(pool: ConnectionPool, principal: Principal, brief: UUID) -> bool:
    if not principal.may_write:
        raise NotAllowed("viewers cannot change briefs")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update briefs set enabled = false where id = %s returning id", (brief,)
        ).fetchone()
        conn.execute(
            "delete from schedules where name = %s and kind = 'brief'",
            (f"brief {brief}",),
        )
        if row:
            record(conn, "brief_stopped", "brief", brief)
    return row is not None


def listing(pool: ConnectionPool, principal: Principal) -> list[dict[str, Any]]:
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            "select b.id, b.template, b.variables, b.cron, b.timezone, b.channel_id, "
            "c.name, b.enabled, b.proposed_by, b.last_body, b.last_run_at, "
            "b.created_at "
            "from briefs b left join channels c on c.id = b.channel_id "
            "order by b.created_at desc"
        ).fetchall()
    out = []
    for bid, tpl, variables, cron, tz, ch, ch_name, on, by, body, ran, at in rows:
        out.append(
            {
                "id": str(bid),
                "template": tpl,
                "title": TEMPLATES[tpl].title,
                "variables": variables,
                "cron": cron,
                "timezone": tz,
                "channel": {"id": str(ch), "name": ch_name} if ch else None,
                "enabled": on,
                "proposed_by": by,
                "last": parse_block(body) if body else None,
                "last_run_at": ran.isoformat() if ran else None,
                "created_at": at.isoformat(),
            }
        )
    return out


def run(ctx: Any) -> dict[str, Any]:
    """The `brief` job: render it now and put it in the outbox."""
    svc = ctx.services
    principal = ctx.job.principal
    brief = UUID(ctx.job.payload["brief_id"])
    with svc.pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select template, variables, timezone, channel_id, enabled from briefs "
            "where id = %s",
            (brief,),
        ).fetchone()
    if row is None or not row[4]:
        return {"skipped": "no such enabled brief"}
    template, variables, timezone, channel, _ = row
    open_markets: dict[str, BinaryMarket] = {}
    if template == "disagreements":
        from vp.domains import DOMAINS
        from vp.markets.store import read_markets

        svc.refresh(list(DOMAINS))
        for domain in DOMAINS:
            snaps = sorted((svc.shared.root / "snapshots" / domain).glob("*.parquet"))
            if snaps:
                open_markets.update(
                    {m.market_id: m for m in read_markets(snaps[-1]) if m.market_id}
                )
    with svc.pool.connection() as conn, tenant_session(conn, principal):
        text, rows = render(conn, template, variables, timezone, open_markets)
        conn.execute(
            "update briefs set last_body = %s, last_run_at = now() where id = %s",
            (text, brief),
        )
        if channel is not None:
            conn.execute(
                "insert into outbox (channel_id, kind, payload) "
                "values (%s, 'brief', %s)",
                (channel, Jsonb({"text": text, "subject": TEMPLATES[template].title})),
            )
    if channel is not None:
        # Send it now rather than at the next minute's delivery round.
        from vp.platform.jobs import PRIORITY_INTERACTIVE, enqueue_platform

        enqueue_platform(svc.pool, "deliver", priority=PRIORITY_INTERACTIVE)
    return {"rows": len(rows), "delivered_to": str(channel) if channel else None}
