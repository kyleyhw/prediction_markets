"""Strategies in a workspace: conversations, versions, memory, lifecycle.

The engine's spec (`vp.strategy.spec`) is stored as it was confirmed: a
version row carries the spec, its hash and its rendering, and is never
edited (a trigger refuses it). Confirming reads the spec from the stored
assistant turn and validates it again, so what a browser sends is only
which turn to confirm, never a spec. Each version that goes to paper gets a
paper account of its own and two schedules (its cycle at the spec's
cadence, and settlement hourly), so a strategy's P&L is its own
(docs/strategies.md, lifecycle).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, LiteralString
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from vp.domains.pack import parse as parse_pack
from vp.platform.db import tenant_session
from vp.platform.principal import Principal
from vp.strategy.spec import Caps, Spec, diff, render, spec_hash, validate

#: What a compile holds against the budget until its cost is known.
COMPILE_RESERVE_USD = 0.25
#: The most memory notes a person keeps.
MEMORY_LIMIT = 50

STATUS_ORDER = ("draft", "previewed", "backtested", "paper", "retired")


class NotFound(LookupError):
    """No such row in this workspace."""


def _rows(
    pool: ConnectionPool, principal: Principal, sql: LiteralString, args: tuple = ()
) -> list[dict[str, Any]]:
    with pool.connection() as conn, tenant_session(conn, principal):
        return conn.cursor(row_factory=dict_row).execute(sql, args).fetchall()


# ------------------------------------------------------------ conversations


def open_conversation(
    pool: ConnectionPool, principal: Principal, strategy_id: UUID | None = None
) -> UUID:
    with pool.connection() as conn, tenant_session(conn, principal):
        if strategy_id is not None:
            found = conn.execute(
                "select 1 from strategies where id = %s", (strategy_id,)
            ).fetchone()
            if found is None:
                raise NotFound("no such strategy")
        row = conn.execute(
            "insert into conversations (strategy_id) values (%s) returning id",
            (strategy_id,),
        ).fetchone()
    assert row is not None
    return row[0]


def conversation(
    pool: ConnectionPool, principal: Principal, conversation_id: UUID
) -> dict[str, Any]:
    rows = _rows(
        pool,
        principal,
        "select id, strategy_id, cost_usd, created_at from conversations where id = %s",
        (conversation_id,),
    )
    if not rows:
        raise NotFound("no such conversation")
    turns = _rows(
        pool,
        principal,
        "select id, role, content, created_at from conversation_turns "
        "where conversation_id = %s order by id",
        (conversation_id,),
    )
    head = rows[0]
    return {
        "id": str(head["id"]),
        "strategy_id": str(head["strategy_id"]) if head["strategy_id"] else None,
        "cost_usd": float(head["cost_usd"]),
        "turns": [
            {
                "id": t["id"],
                "role": t["role"],
                "content": t["content"],
                "at": t["created_at"].isoformat(),
            }
            for t in turns
        ],
    }


def add_turns(
    pool: ConnectionPool,
    principal: Principal,
    conversation_id: UUID,
    turns: list[tuple[str, dict[str, Any]]],
    cost_usd: float,
) -> None:
    with pool.connection() as conn, tenant_session(conn, principal):
        for role, content in turns:
            conn.execute(
                "insert into conversation_turns (conversation_id, role, content) "
                "values (%s, %s, %s)",
                (conversation_id, role, Jsonb(content)),
            )
        conn.execute(
            "update conversations set cost_usd = cost_usd + %s, updated_at = now() "
            "where id = %s",
            (cost_usd, conversation_id),
        )


def history(convo: dict[str, Any]) -> list[tuple[str, str]]:
    """A conversation's turns as the compiler's ``(role, text)`` history."""
    out: list[tuple[str, str]] = []
    for turn in convo["turns"]:
        content = turn["content"]
        if turn["role"] == "user":
            out.append(("user", content["words"]))
        else:
            text = content.get("message") or ""
            if content.get("rendering"):
                text += "\nProposed:\n" + "\n".join(content["rendering"])
            out.append(("assistant", text or content.get("kind", "")))
    return out


# ----------------------------------------------------------------- versions


def latest(
    pool: ConnectionPool, principal: Principal, strategy_id: UUID
) -> dict[str, Any]:
    """The strategy and its newest version, with the spec parsed."""
    rows = _rows(
        pool,
        principal,
        "select s.id, s.name, s.status, v.id as version_id, v.version, v.spec, "
        "v.spec_hash, v.rendering from strategies s join strategy_versions v "
        "on v.strategy_id = s.id where s.id = %s order by v.version desc limit 1",
        (strategy_id,),
    )
    if not rows:
        raise NotFound("no such strategy")
    row = rows[0]
    row["spec"] = Spec.model_validate(row["spec"])
    return row


def confirm(
    pool: ConnectionPool,
    principal: Principal,
    conversation_id: UUID,
    turn_id: int,
    caps: Caps = Caps(),
) -> dict[str, Any]:
    """Freeze the spec of an assistant turn as a version; returns its ids.

    The first confirmation in a conversation makes a strategy; one in a
    conversation about a strategy adds its next version.
    """
    convo = conversation(pool, principal, conversation_id)
    turn = next(
        (t for t in convo["turns"] if t["id"] == turn_id and t["role"] == "assistant"),
        None,
    )
    if turn is None or not turn["content"].get("spec"):
        raise NotFound("that turn proposed no strategy")
    spec = Spec.model_validate(turn["content"]["spec"])
    problems = validate(spec, caps)
    if problems:
        raise ValueError(" ".join(problems))
    digest = spec_hash(spec)
    with pool.connection() as conn, tenant_session(conn, principal):
        strategy_id = convo["strategy_id"]
        if strategy_id is None:
            row = conn.execute(
                "insert into strategies (name, created_by) values (%s, %s) "
                "returning id",
                (spec.name, principal.user_id),
            ).fetchone()
            assert row is not None
            strategy_id, version = row[0], 1
            conn.execute(
                "update conversations set strategy_id = %s where id = %s",
                (strategy_id, conversation_id),
            )
        else:
            row = conn.execute(
                "select coalesce(max(version), 0) + 1, "
                "(array_agg(spec_hash order by version desc))[1] "
                "from strategy_versions where strategy_id = %s",
                (strategy_id,),
            ).fetchone()
            assert row is not None
            if row[1] == digest:
                raise ValueError("this is the version already in use")
            version = row[0]
            conn.execute(
                "update strategies set name = %s, updated_at = now(), "
                "status = case when status = 'retired' then status else 'draft' end "
                "where id = %s",
                (spec.name, strategy_id),
            )
        row = conn.execute(
            "insert into strategy_versions (strategy_id, version, spec, spec_hash, "
            "rendering, created_by) values (%s, %s, %s, %s, %s, %s) returning id",
            (
                strategy_id,
                version,
                Jsonb(spec.model_dump(mode="json")),
                digest,
                render(spec),
                principal.user_id,
            ),
        ).fetchone()
    assert row is not None
    return {
        "strategy_id": str(strategy_id),
        "version_id": str(row[0]),
        "version": version,
        "spec_hash": digest,
    }


def advance(
    pool: ConnectionPool, principal: Principal, strategy_id: UUID, status: str
) -> None:
    """Move the status forward (never back, and never out of retired)."""
    later = STATUS_ORDER[STATUS_ORDER.index(status) :]
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "update strategies set status = %s, updated_at = now() "
            "where id = %s and status <> 'retired' and not (status = any(%s))",
            (status, strategy_id, list(later)),
        )


def listing(pool: ConnectionPool, principal: Principal) -> list[dict[str, Any]]:
    rows = _rows(
        pool,
        principal,
        "select distinct on (s.id) s.id, s.name, s.status, s.updated_at, v.version, "
        "v.spec_hash, v.rendering from strategies s join strategy_versions v "
        "on v.strategy_id = s.id order by s.id, v.version desc",
    )
    rows.sort(key=lambda r: r["updated_at"], reverse=True)
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "status": r["status"],
            "version": r["version"],
            "spec_hash": r["spec_hash"],
            "rendering": r["rendering"],
            "updated_at": r["updated_at"].isoformat(),
        }
        for r in rows
    ]


def detail(
    pool: ConnectionPool, principal: Principal, strategy_id: UUID
) -> dict[str, Any]:
    """The strategy, every version with what changed, its runs and accounts."""
    head = _rows(
        pool,
        principal,
        "select id, name, status, created_at from strategies where id = %s",
        (strategy_id,),
    )
    if not head:
        raise NotFound("no such strategy")
    versions = _rows(
        pool,
        principal,
        "select id, version, spec, spec_hash, rendering, created_at "
        "from strategy_versions where strategy_id = %s order by version",
        (strategy_id,),
    )
    ids = [v["id"] for v in versions]
    runs = _rows(
        pool,
        principal,
        "select id, strategy_version_id, config, results, manifest_hash, created_at "
        "from runs where strategy_version_id = any(%s) order by created_at desc",
        (ids,),
    )
    accounts = _rows(
        pool,
        principal,
        "select id, name, strategy_version_id, initial_cash, created_at "
        "from paper_accounts where strategy_version_id = any(%s) "
        "order by created_at",
        (ids,),
    )
    out_versions = []
    previous: Spec | None = None
    for v in versions:
        spec = Spec.model_validate(v["spec"])
        out_versions.append(
            {
                "id": str(v["id"]),
                "version": v["version"],
                "spec": v["spec"],
                "spec_hash": v["spec_hash"],
                "rendering": v["rendering"],
                "changes": [list(c) for c in diff(previous, spec)] if previous else [],
                "created_at": v["created_at"].isoformat(),
            }
        )
        previous = spec
    number = {v["id"]: v["version"] for v in versions}
    return {
        "id": str(head[0]["id"]),
        "name": head[0]["name"],
        "status": head[0]["status"],
        "versions": out_versions,
        "runs": [
            {
                "run_id": str(r["id"]),
                "version": number.get(r["strategy_version_id"]),
                "domain": r["config"].get("domain"),
                "results": r["results"],
                "manifest_hash": r["manifest_hash"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in runs
        ],
        "accounts": [
            {
                "id": str(a["id"]),
                "name": a["name"],
                "version": number.get(a["strategy_version_id"]),
                "initial_cash": float(a["initial_cash"]),
                "created_at": a["created_at"].isoformat(),
            }
            for a in accounts
        ],
    }


# -------------------------------------------------------------------- paper


def start_paper(
    pool: ConnectionPool,
    principal: Principal,
    strategy_id: UUID,
    dataset_versions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Open a paper account for the newest version and schedule it.

    Idempotent per version: asking again returns the version's account. A
    new account's ledger starts with the run manifest (spec hash, packs,
    dataset versions, packages), so the paper period's record says what
    produced it, inside the hash chain.
    """
    from vp.platform.ledger import PgLedger
    from vp.strategy.card import manifest

    head = latest(pool, principal, strategy_id)
    if head["status"] == "retired":
        raise ValueError("a retired strategy does not trade")
    spec: Spec = head["spec"]
    name = f"{head['name']} v{head['version']}"[:100]
    with pool.connection() as conn, tenant_session(conn, principal):
        row = conn.execute(
            "select id from paper_accounts where strategy_version_id = %s",
            (head["version_id"],),
        ).fetchone()
        opened = row is None
        if opened:
            row = conn.execute(
                "insert into paper_accounts (name, domains, forecasters, "
                "initial_cash, created_by, strategy_version_id) "
                "values (%s, %s, %s, %s, %s, %s) returning id",
                (
                    name,
                    spec.selector.domains,
                    [_belief_name(spec)],
                    spec.sizing.initial_cash,
                    principal.user_id,
                    head["version_id"],
                ),
            ).fetchone()
            assert row is not None
            every = spec.schedule.cadence_hours
            cron = "5 * * * *" if every == 1 else f"5 */{every} * * *"
            now = datetime.now(tz=UTC)
            for label, kind, when in (
                ("cycle", "paper_cycle", cron),
                ("settle", "settle", "35 * * * *"),
            ):
                conn.execute(
                    "insert into schedules (workspace_id, created_by, name, kind, "
                    "payload, cron, next_run_at) values (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        principal.workspace,
                        principal.user_id,
                        f"{label} {row[0]}",
                        kind,
                        Jsonb({"account_id": str(row[0])}),
                        when,
                        now,
                    ),
                )
    assert row is not None
    account_id = row[0]
    if opened:
        packs = workspace_packs(pool, principal)
        PgLedger(pool, principal, account_id).append(
            "manifest",
            {
                "strategy_version": head["version"],
                "domains": {
                    d: manifest(
                        spec,
                        domain=d,
                        dataset_version=(dataset_versions or {}).get(d, "unknown"),
                        packs=packs,
                    )
                    for d in spec.selector.domains
                },
            },
        )
    advance(pool, principal, strategy_id, "paper")
    return {"account_id": str(account_id), "version": head["version"]}


def _belief_name(spec: Spec) -> str:
    from vp.strategy.run import FOLLOW

    return FOLLOW if spec.rule.kind == "follow" else spec.belief.forecaster


def retire(pool: ConnectionPool, principal: Principal, strategy_id: UUID) -> None:
    """Stop a strategy: its schedules are switched off; its records stay."""
    detail_ = detail(pool, principal, strategy_id)
    accounts = [a["id"] for a in detail_["accounts"]]
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "update schedules set enabled = false "
            "where payload->>'account_id' = any(%s)",
            (accounts,),
        )
        conn.execute(
            "update strategies set status = 'retired', updated_at = now() "
            "where id = %s",
            (strategy_id,),
        )


def version_spec(
    pool: ConnectionPool, principal: Principal, version_id: UUID
) -> tuple[Spec, str, UUID]:
    """A version's spec, hash and strategy id."""
    rows = _rows(
        pool,
        principal,
        "select spec, spec_hash, strategy_id from strategy_versions where id = %s",
        (version_id,),
    )
    if not rows:
        raise NotFound("no such strategy version")
    return (
        Spec.model_validate(rows[0]["spec"]),
        rows[0]["spec_hash"],
        rows[0]["strategy_id"],
    )


# ------------------------------------------------------------------- memory


def memory(pool: ConnectionPool, principal: Principal) -> list[dict[str, Any]]:
    rows = _rows(
        pool,
        principal,
        "select id, note, created_at from user_memory order by created_at",
    )
    return [
        {"id": str(r["id"]), "note": r["note"], "at": r["created_at"].isoformat()}
        for r in rows
    ]


def remember(pool: ConnectionPool, principal: Principal, note: str) -> str:
    note = " ".join(note.split())
    if not note:
        raise ValueError("a note needs words")
    with pool.connection() as conn, tenant_session(conn, principal):
        count = conn.execute("select count(*) from user_memory").fetchone()
        if count and count[0] >= MEMORY_LIMIT:
            raise ValueError(f"at most {MEMORY_LIMIT} notes; delete one first")
        row = conn.execute(
            "insert into user_memory (note) values (%s) returning id", (note,)
        ).fetchone()
    assert row is not None
    return str(row[0])


def forget(pool: ConnectionPool, principal: Principal, note_id: UUID) -> bool:
    with pool.connection() as conn, tenant_session(conn, principal):
        return (
            conn.execute("delete from user_memory where id = %s", (note_id,)).rowcount
            > 0
        )


# -------------------------------------------------------------------- packs


def workspace_packs(pool: ConnectionPool, principal: Principal) -> dict[str, str]:
    rows = _rows(pool, principal, "select domain, body from domain_packs")
    return {r["domain"]: r["body"] for r in rows}


def save_pack(
    pool: ConnectionPool, principal: Principal, domain: str, body: str
) -> str:
    pack = parse_pack(body)
    if pack.domain != domain:
        raise ValueError("the pack's frontmatter names another domain")
    with pool.connection() as conn, tenant_session(conn, principal):
        conn.execute(
            "insert into domain_packs (domain, body, sha256, updated_by) "
            "values (%s, %s, %s, %s) on conflict (workspace_id, domain) do update "
            "set body = excluded.body, sha256 = excluded.sha256, "
            "updated_by = excluded.updated_by, updated_at = now()",
            (domain, body, pack.sha256, principal.user_id),
        )
    return pack.sha256


def drop_pack(pool: ConnectionPool, principal: Principal, domain: str) -> bool:
    with pool.connection() as conn, tenant_session(conn, principal):
        return (
            conn.execute(
                "delete from domain_packs where domain = %s", (domain,)
            ).rowcount
            > 0
        )
