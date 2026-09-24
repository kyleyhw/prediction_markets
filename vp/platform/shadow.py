"""Shadow imports on the platform (docs/shadow.md, Phase 19): consent, the
import job, the optional proof of ownership, and the card.

An import is the person's own (migration 0024). The job reads the address's
public record from the venue, keeps the raw activity in the object store as
the import's evidence, and stores the card beside the import.
"""

from __future__ import annotations

import gzip
import json
import secrets
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.platform import jobs
from vp.platform.db import tenant_session
from vp.platform.principal import Principal
from vp.shadow import proof

CONSENT_VERSION = "shadow-1"
CONSENT = (
    "This address's trades are public on the venue. Linking it to my account "
    "is my choice; the platform reads its public record and keeps it with my "
    "account until I delete the import."
)
CAP, HISTORIES = 50_000, 300


def start(pool: ConnectionPool, principal: Principal, address: str) -> dict[str, Any]:
    """Record the consent and queue the import (again, if it exists)."""
    from vp.venues.polymarket import ADDRESS

    address = address.strip().lower()
    if not ADDRESS.match(address):
        raise ValueError("that is not an address (0x and 40 hex digits)")
    if not principal.may_write:
        raise PermissionError("viewers cannot import a record")
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "insert into shadow_imports (address, consent_version, nonce) "
            "values (%s, %s, %s) on conflict (user_id, workspace_id, address) do "
            "update set state = 'queued', error = null, updated_at = now(), "
            "consent_version = excluded.consent_version, consented_at = now() "
            "returning id",
            (address, CONSENT_VERSION, secrets.token_hex(8)),
        ).fetchone()
    assert row is not None
    job = jobs.enqueue(pool, principal, "shadow_import", {"import_id": str(row[0])})
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "update shadow_imports set job_id = %s where id = %s", (job, row[0])
        )
    return {"id": str(row[0]), "job_id": str(job)}


def _row(r: tuple[Any, ...], with_card: bool) -> dict[str, Any]:
    iid, address, state, verified, error, at, nonce, card = r
    out = {
        "id": str(iid),
        "address": address,
        "state": state,
        "verified": verified is not None,
        "error": error,
        "updated_at": at.isoformat(),
        "message": proof.message(address, nonce),
    }
    if with_card:
        out["card"] = card
    elif card:
        out["summary"] = card.get("diagnostics", {}).get("overall")
    return out


_COLUMNS = "id, address, state, verified_at, error, updated_at, nonce, card"


def listing(pool: ConnectionPool, principal: Principal) -> list[dict[str, Any]]:
    with pool.connection() as conn, tenant_session(conn, principal):
        rows = conn.execute(
            f"select {_COLUMNS} from shadow_imports order by updated_at desc"
        ).fetchall()
    return [_row(r, False) for r in rows]


def get(pool: ConnectionPool, principal: Principal, iid: UUID) -> dict[str, Any] | None:
    with pool.connection() as conn, tenant_session(conn, principal):
        r = conn.execute(
            f"select {_COLUMNS} from shadow_imports where id = %s", (iid,)
        ).fetchone()
    return _row(r, True) if r else None


def delete(pool: ConnectionPool, principal: Principal, iid: UUID) -> bool:
    with pool.connection() as conn, tenant_session(conn, principal):
        cur = conn.execute("delete from shadow_imports where id = %s", (iid,))
    return bool(cur.rowcount)


def verify(
    pool: ConnectionPool, principal: Principal, iid: UUID, signature: str, profile: Any
) -> bool:
    """Check a signature of the import's message; mark it verified if it holds."""
    with pool.connection() as conn, tenant_session(conn, principal):
        r = conn.execute(
            "select address, nonce from shadow_imports where id = %s", (iid,)
        ).fetchone()
    if r is None:
        raise LookupError("no such import")
    address, nonce = r
    text = proof.message(address, nonce)
    if not proof.owns(address, text, signature, profile):
        return False
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "update shadow_imports set verified_at = now(), verified_by = %s, "
            "nonce = %s where id = %s",
            (proof.recover(text, signature), secrets.token_hex(8), iid),
        )
    return True


def run(ctx: Any) -> dict[str, Any]:
    """The `shadow_import` job."""
    from vp.domains import DOMAINS
    from vp.shadow import card
    from vp.venues import polymarket

    svc, principal = ctx.services, ctx.job.principal
    iid = UUID(ctx.job.payload["import_id"])
    with svc.pool.connection() as conn, tenant_session(conn, principal):
        r = conn.execute(
            "update shadow_imports set state = 'running', updated_at = now() "
            "where id = %s returning address",
            (iid,),
        ).fetchone()
    if r is None:
        return {"skipped": "the import was deleted"}
    address = r[0]
    try:
        ctx.progress(0.0, "reading the record")
        activity = list(polymarket.fetch_activity(address, max_items=CAP))
        svc.store.put_bytes(
            f"shadow/{principal.workspace}/{iid}/activity.json.gz",
            gzip.compress(json.dumps(activity).encode()),
        )
        svc.refresh(list(DOMAINS))
        result = card.analyse(
            address,
            activity,
            svc.shared.root,
            resolve=polymarket.fetch_resolution,
            history=card.venue_history,
            leaderboard=lambda c: polymarket.fetch_leaderboard(c, limit=50),
            pnl=polymarket.fetch_user_pnl,
            cap=CAP,
            max_histories=HISTORIES,
            progress=lambda f, m: ctx.progress(0.05 + 0.9 * f, m),
        )
    except Exception as exc:
        with svc.pool.connection() as conn, tenant_session(conn, principal):
            conn.execute(
                "update shadow_imports set state = 'failed', error = %s, "
                "updated_at = now() where id = %s",
                (f"{type(exc).__name__}: {exc}"[:500], iid),
            )
        raise
    with svc.pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "update shadow_imports set state = 'done', card = %s, error = null, "
            "updated_at = now() where id = %s",
            (Jsonb(result), iid),
        )
    return {"bets": result["record"]["bets"], "scored": result["record"]["scored"]}


def try_rule(
    pool: ConnectionPool, principal: Principal, iid: UUID, domain: str, index: int
) -> str:
    """Open a conversation holding a validated rule's spec, for the person to
    read and confirm like any other (docs/strategies.md)."""
    from vp.platform import strategies
    from vp.strategy.spec import Spec, render

    found = get(pool, principal, iid)
    if found is None or not found.get("card"):
        raise LookupError("no such import, or it has no card yet")
    try:
        rule = found["card"]["rules"][domain]["rules"][index]
    except KeyError, IndexError:
        raise LookupError("no such rule") from None
    if not rule.get("validated") or not rule.get("spec"):
        raise ValueError("only a validated rule becomes a strategy")
    spec = Spec.model_validate(rule["spec"])
    convo = strategies.open_conversation(pool, principal)
    content = {
        "kind": "spec",
        "message": "This is the rule found in your record. Nothing runs until you "
        "confirm it; you can change anything first.",
        "choices": [],
        "remember": [],
        "spec": spec.model_dump(mode="json"),
        "rendering": render(spec),
        "changes": [],
        "problems": [],
        "cost_usd": 0.0,
        "model": None,
    }
    strategies.add_turns(
        pool,
        principal,
        convo,
        [
            ("user", {"words": f"From my record: {rule['words']}"}),
            ("assistant", content),
        ],
        0.0,
    )
    return str(convo)
