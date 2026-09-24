"""Public links to strategies, forks and strategy cards (plan, task 82;
docs/collaboration.md).

A share publishes a snapshot, never a live view: what the publisher saw,
refreshed when they ask and daily. The public reads it only through
`vp_share_view`. By default it holds the strategy's rendering, its newest
run card per domain and its leaderboard standing; its paper P&L, its spec
(and so whether it can be forked) and its author are each the publisher's
choice. A fork is a new strategy in the forker's workspace whose first
version is the shared spec, with where it came from recorded.
"""

from __future__ import annotations

import html
import secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.platform.db import tenant_session
from vp.platform.principal import Principal
from vp.platform.teams import NotAllowed, record
from vp.strategy.spec import Caps, Spec, render, spec_hash, validate


def _snapshot(
    conn: psycopg.Connection, strategy_id: UUID, flags: dict[str, bool]
) -> dict[str, Any]:
    head = conn.execute(
        "select s.name, v.version, v.spec, v.spec_hash, v.rendering, u.email "
        "from strategies s join strategy_versions v on v.strategy_id = s.id "
        "left join users u on u.id = s.created_by where s.id = %s "
        "order by v.version desc limit 1",
        (strategy_id,),
    ).fetchone()
    if head is None:
        raise LookupError("no such strategy, or it has no version yet")
    name, version, spec, digest, rendering, email = head
    cards = [
        r[0]
        for r in conn.execute(
            "select distinct on (r.config ->> 'domain') r.results -> 'card' "
            "from runs r join strategy_versions v on v.id = r.strategy_version_id "
            "where v.strategy_id = %s and r.results ? 'card' "
            "order by r.config ->> 'domain', r.created_at desc",
            (strategy_id,),
        ).fetchall()
        if r[0]
    ]
    out: dict[str, Any] = {
        "name": name,
        "version": version,
        "spec_hash": digest,
        "rendering": list(rendering),
        "cards": cards,
        "published_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "forkable": flags["show_spec"],
        "author": email.split("@")[0] if flags["show_author"] and email else None,
    }
    if flags["show_spec"]:
        out["spec"] = spec
    if flags["show_pnl"]:
        row = conn.execute(
            "select count(*), coalesce(sum((e.entry -> 'data' ->> 'pnl')::float), 0), "
            "avg((e.entry -> 'data' ->> 'brier')::float), "
            "avg((e.entry -> 'data' ->> 'brier_market')::float), min(e.at) "
            "from ledger_entries e join paper_accounts a on a.id = e.account_id "
            "join strategy_versions v on v.id = a.strategy_version_id "
            "where v.strategy_id = %s and e.kind = 'settlement'",
            (strategy_id,),
        ).fetchone()
        n, pnl, brier, market, since = row or (0, 0, None, None, None)
        out["paper"] = {
            "settled": n,
            "realised": round(pnl, 2),
            "skill": (1 - brier / market) if brier is not None and market else None,
            "since": since.isoformat() if since else None,
        }
    board = conn.execute(
        "select board, entry from leaderboards, "
        "jsonb_array_elements(body -> 'entries') entry "
        "where entry ->> 'strategy_id' = %s",
        (str(strategy_id),),
    ).fetchall()
    out["standing"] = [{"board": b, **e} for b, e in board]
    return out


def publish(
    pool: ConnectionPool,
    principal: Principal,
    strategy_id: UUID,
    *,
    show_pnl: bool = False,
    show_spec: bool = False,
    show_author: bool = False,
) -> dict[str, Any]:
    """Make (or update) the strategy's public link; returns slug and snapshot."""
    if not principal.may_write:
        raise NotAllowed("viewers cannot publish")
    flags = {"show_pnl": show_pnl, "show_spec": show_spec, "show_author": show_author}
    with pool.connection() as conn, tenant_session(conn, principal):
        snapshot = _snapshot(conn, strategy_id, flags)
        row = conn.execute(
            "update shares set show_pnl = %s, show_spec = %s, show_author = %s, "
            "snapshot = %s, refreshed_at = now() where strategy_id = %s "
            "and revoked_at is null returning slug",
            (show_pnl, show_spec, show_author, Jsonb(snapshot), strategy_id),
        ).fetchone()
        if row is None:
            slug = secrets.token_urlsafe(18)
            conn.execute(
                "insert into shares (strategy_id, slug, show_pnl, show_spec, "
                "show_author, snapshot, created_by) "
                "values (%s, %s, %s, %s, %s, %s, %s)",
                (
                    strategy_id,
                    slug,
                    show_pnl,
                    show_spec,
                    show_author,
                    Jsonb(snapshot),
                    principal.user_id,
                ),
            )
            record(conn, "shared", "strategy", strategy_id, flags)
        else:
            slug = row[0]
            record(conn, "share_updated", "strategy", strategy_id, flags)
    return {"slug": slug, "snapshot": snapshot}


def refresh_all(pool: ConnectionPool, principal: Principal) -> int:
    """Refresh every live share in the workspace (the daily job)."""
    with pool.connection() as conn, tenant_session(conn, principal):
        live = conn.execute(
            "select strategy_id, show_pnl, show_spec, show_author from shares "
            "where revoked_at is null"
        ).fetchall()
        for sid, pnl, spec, author in live:
            flags = {"show_pnl": pnl, "show_spec": spec, "show_author": author}
            conn.execute(
                "update shares set snapshot = %s, refreshed_at = now() "
                "where strategy_id = %s and revoked_at is null",
                (Jsonb(_snapshot(conn, sid, flags)), sid),
            )
    return len(live)


def mine(pool: ConnectionPool, principal: Principal, strategy_id: UUID) -> dict | None:
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select slug, show_pnl, show_spec, show_author, views, forks, "
            "refreshed_at from shares where strategy_id = %s and revoked_at is null",
            (strategy_id,),
        ).fetchone()
    if row is None:
        return None
    slug, pnl, spec, author, views, forks, at = row
    return {
        "slug": slug,
        "show_pnl": pnl,
        "show_spec": spec,
        "show_author": author,
        "views": views,
        "forks": forks,
        "refreshed_at": at.isoformat(),
    }


def revoke(pool: ConnectionPool, principal: Principal, strategy_id: UUID) -> bool:
    if not principal.may_write:
        raise NotAllowed("viewers cannot unpublish")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "update shares set revoked_at = now() where strategy_id = %s "
            "and revoked_at is null returning id",
            (strategy_id,),
        ).fetchone()
        if row:
            record(conn, "unshared", "strategy", strategy_id)
    return row is not None


def view(pool: ConnectionPool, slug: str, *, count: bool = True) -> dict | None:
    """The public snapshot of a live share, or None."""
    with pool.connection() as conn:
        row = conn.execute("select vp_share_view(%s, %s)", (slug, count)).fetchone()
    return row[0] if row else None


def fork(
    pool: ConnectionPool, principal: Principal, slug: str, caps: Caps = Caps()
) -> dict[str, Any]:
    """Copy a shared spec into the principal's workspace as a new strategy."""
    if not principal.may_write:
        raise NotAllowed("viewers cannot fork")
    snapshot = view(pool, slug, count=False)
    if snapshot is None:
        raise LookupError("no such share")
    if not snapshot.get("forkable") or "spec" not in snapshot:
        raise NotAllowed("the publisher did not share this strategy's spec")
    spec = Spec.model_validate(snapshot["spec"])
    problems = validate(spec, caps)
    if problems:
        raise ValueError(" ".join(problems))
    digest = spec_hash(spec)
    provenance = {
        "forked_from": slug,
        "spec_hash": digest,
        "source_version": snapshot.get("version"),
        "at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
    }
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "insert into strategies (name, created_by, provenance) "
            "values (%s, %s, %s) returning id",
            (spec.name, principal.user_id, Jsonb(provenance)),
        ).fetchone()
        assert row is not None
        (sid,) = row
        row = conn.execute(
            "insert into strategy_versions (strategy_id, version, spec, spec_hash, "
            "rendering, created_by) values (%s, 1, %s, %s, %s, %s) returning id",
            (
                sid,
                Jsonb(spec.model_dump(mode="json")),
                digest,
                render(spec),
                principal.user_id,
            ),
        ).fetchone()
        assert row is not None
        (vid,) = row
        record(conn, "forked", "strategy", sid, provenance)
        conn.execute("select vp_share_forked(%s)", (slug,))
    return {"strategy_id": str(sid), "version_id": str(vid), "provenance": provenance}


def card_svg(snapshot: dict[str, Any]) -> str:
    """The strategy card: name, the rule's first line, and its evidence."""
    esc = html.escape
    lines = snapshot.get("rendering") or []
    card = (snapshot.get("cards") or [{}])[0] or {}
    skill = card.get("skill")
    facts = [
        f"{card.get('scored', 0)} markets scored" if card else "no backtest yet",
        f"skill {skill:+.3f} against the market" if skill is not None else "",
    ]
    paper = snapshot.get("paper")
    if paper:
        facts.append(f"paper: {paper['settled']} settled, {paper['realised']:+.2f} USD")
    body = "".join(
        f'<text x="24" y="{112 + 22 * i}" font-size="15">{esc(t)}</text>'
        for i, t in enumerate(f for f in facts if f)
    )
    first = esc((lines[0] if lines else "")[:90])
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="200" '
        'viewBox="0 0 600 200" role="img" '
        f'aria-label="{esc(snapshot.get("name", "Strategy"))}">'
        '<rect width="600" height="200" rx="12" fill="#faf8f3" stroke="#1d1d1b"/>'
        '<g font-family="Instrument Sans, system-ui, sans-serif" fill="#1d1d1b">'
        f'<text x="24" y="44" font-size="24" font-weight="600">'
        f"{esc(snapshot.get('name', ''))[:40]}</text>"
        f'<text x="24" y="76" font-size="14">{first}</text>{body}'
        '<text x="576" y="184" font-size="12" text-anchor="end">vibe-predict</text>'
        "</g></svg>"
    )
