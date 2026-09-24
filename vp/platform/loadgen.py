"""Synthetic workspaces and the probes of the scale proof (docs/scaling.md
§ 14, plan task 105).

`seed` creates people, workspaces, paper accounts and a day of ledger
entries each with valid hash chains, by COPY as the owner (a day of 10,000
people is a million entries). The probes measure one component each against
its objective: ledger appends, the cost of a trading cycle's chain check as
a chain grows, job claims under a deep queue, and the web's cached views
under concurrency. Everything it writes is tagged ``load-<tag>`` and removed
by `remove`. It is an operator's tool (`vp admin load`), never a user's.
"""

from __future__ import annotations

import json
import random
import socket
import statistics
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg

from vp.paper.ledger import GENESIS, entry_hash, verify_entries
from vp.platform.auth import digest, new_secret
from vp.platform.legal import TERMS_VERSION

ENTRIES_PER_DAY = 100  # the capacity model's per-person ledger rate


def _chain(n: int, at: str, rng: random.Random) -> list[dict[str, Any]]:
    """A valid chain of ``n`` order and settlement entries, field for field
    as the paper loop writes them."""
    out, prev, bankroll = [], GENESIS, 1000.0
    for seq in range(n):
        kind = "order" if seq % 2 == 0 else "settlement"
        market = f"m{seq // 2}"
        data: dict[str, Any] = {"forecaster": "elo", "market_id": market}
        if kind == "order":
            q = round(rng.uniform(0.2, 0.8), 3)
            data |= {
                "condition_id": f"c{seq // 2}",
                "event_id": f"e{seq // 6}",
                "domain": "load",
                "question": f"Synthetic market {seq // 2}?",
                "side": "yes",
                "price": q,
                "shares": 10 / q,
                "stake": 10.0,
                "fee": 0.0,
                "fee_rate": 0.0,
                "fee_source": "market",
                "p_hat": q,
                "q": q,
                "bankroll_before": bankroll,
            }
        else:
            won = rng.random() < 0.5
            pnl = round(10 / out[-1]["data"]["price"] - 10 if won else -10.0, 4)
            bankroll += pnl
            data |= {
                "label": int(won),
                "pnl": pnl,
                "brier": 0.2,
                "brier_market": 0.2,
                "bankroll_after": bankroll,
            }
        entry = {"seq": seq, "at": at, "kind": kind, "data": data, "prev": prev}
        entry["hash"] = entry_hash(entry)
        out.append(entry)
        prev = entry["hash"]
    return out


def seed(
    conn: psycopg.Connection,
    tag: str,
    people: int,
    entries: int = ENTRIES_PER_DAY,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Create ``people`` people, each owning a workspace and a paper account
    with ``entries`` ledger entries; returns counts and timings."""
    rng = random.Random(tag)
    at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    t0 = time.perf_counter()
    rows = []
    for i in range(people):
        rows.append((uuid4(), uuid4(), uuid4(), f"load-{tag}-{i}@example.test"))
    with conn.transaction():
        with conn.cursor().copy("copy workspaces (id, name) from stdin") as cp:
            for _, ws, _, _ in rows:
                cp.write_row((ws, f"load-{tag}"))
        with conn.cursor().copy(
            "copy users (id, email, terms_version, terms_accepted_at, "
            "adult_confirmed_at) from stdin"
        ) as cp:
            for user, _, _, email in rows:
                cp.write_row((user, email, TERMS_VERSION, at, at))
        with conn.cursor().copy(
            "copy memberships (workspace_id, user_id, role) from stdin"
        ) as cp:
            for user, ws, _, _ in rows:
                cp.write_row((ws, user, "owner"))
        with conn.cursor().copy(
            "copy paper_accounts (id, workspace_id, name, domains, forecasters) "
            "from stdin"
        ) as cp:
            for _, ws, acct, _ in rows:
                cp.write_row((acct, ws, f"load-{tag}", ["load"], ["elo"]))
    t_people = time.perf_counter() - t0
    t1 = time.perf_counter()
    written = 0
    for start in range(0, people, 500):
        chunk = rows[start : start + 500]
        with conn.transaction():
            with conn.cursor().copy(
                "copy ledger_entries (account_id, workspace_id, seq, at, kind, "
                "entry, hash) from stdin"
            ) as cp:
                heads = []
                for _, ws, acct, _ in chunk:
                    chain = _chain(entries, at, rng)
                    for e in chain:
                        cp.write_row(
                            (
                                acct,
                                ws,
                                e["seq"],
                                at,
                                e["kind"],
                                json.dumps(e),
                                e["hash"],
                            )
                        )
                    heads.append((acct, ws, chain[-1]["seq"], chain[-1]["hash"]))
                    written += len(chain)
            with conn.cursor().copy(
                "copy ledger_heads (account_id, workspace_id, seq, hash) from stdin"
            ) as cp:
                for h in heads:
                    cp.write_row(h)
        if progress:
            progress(f"{start + len(chunk)} of {people} people seeded")
    return {
        "people": people,
        "entries": written,
        "people_seconds": round(t_people, 2),
        "ledger_seconds": round(time.perf_counter() - t1, 2),
        "accounts": [(str(u), str(w), str(a)) for u, w, a, _ in rows],
    }


def sessions(
    conn: psycopg.Connection, accounts: list[tuple[str, str, str]]
) -> list[str]:
    """A signed-in session for each (user, workspace, account)."""
    out = []
    with conn.transaction():
        with conn.cursor().copy(
            "copy sessions (session_hash, user_id, workspace_id, expires_at) from stdin"
        ) as cp:
            for user, ws, _ in accounts:
                secret = new_secret()
                out.append(secret)
                cp.write_row((digest(secret), user, ws, "2099-01-01T00:00:00Z"))
    return out


def remove(conn: psycopg.Connection, tag: str) -> int:
    """Delete everything a seed with ``tag`` created."""
    with conn.transaction():
        conn.execute(
            "delete from ledger_entries where workspace_id in "
            "(select id from workspaces where name = %s)",
            (f"load-{tag}",),
        )
        cur = conn.execute("delete from workspaces where name = %s", (f"load-{tag}",))
        conn.execute("delete from users where email like %s", (f"load-{tag}-%",))
    return cur.rowcount


def _quantiles(xs: list[float]) -> dict[str, float]:
    s = sorted(xs)
    pick = lambda f: s[min(len(s) - 1, int(f * len(s)))] * 1000  # noqa: E731
    return {
        "n": len(s),
        "p50_ms": round(pick(0.5), 2),
        "p95_ms": round(pick(0.95), 2),
        "p99_ms": round(pick(0.99), 2),
        "mean_ms": round(statistics.fmean(s) * 1000, 2),
    }


def _appender(args: tuple[str, tuple[str, str, str], float]) -> list[float]:
    """One writer process: single appends onto one account for a while."""
    from psycopg_pool import ConnectionPool

    from vp.platform.ledger import PgLedger
    from vp.platform.principal import AuthMethod, Principal, Role

    url, (user, ws, acct), seconds = args
    with ConnectionPool(url, min_size=1, max_size=1, open=True) as pool:
        ledger = PgLedger(
            pool,
            Principal(user, AuthMethod.JOB, UUID(ws), frozenset({Role.EDITOR})),
            UUID(acct),
        )
        times, stop = [], time.time() + seconds
        while time.time() < stop:
            t = time.perf_counter()
            ledger.append("cycle", {"note": "load"})
            times.append(time.perf_counter() - t)
    return times


def probe_appends(
    url: str, accounts: list[tuple[str, str, str]], writers: int, seconds: float
) -> dict[str, Any]:
    """Single appends from ``writers`` processes on distinct accounts, as
    settlements write them (processes, not threads: one Python process is
    bound by its own interpreter long before the database)."""
    from multiprocessing import get_context

    with get_context("spawn").Pool(writers) as procs:
        t0 = time.time()
        parts = procs.map(
            _appender,
            [(url, accounts[i % len(accounts)], seconds) for i in range(writers)],
        )
        took = time.time() - t0
    times = [x for part in parts for x in part]
    return {
        "writers": writers,
        "per_second": round(len(times) / min(took, seconds + 1), 1),
        **_quantiles(times),
    }


def probe_chain(conn: psycopg.Connection, lengths: list[int]) -> list[dict[str, Any]]:
    """What a trading cycle's full-chain check and replay cost as a chain
    grows (one account per length, in memory: the database read is added by
    `probe_chain_read`)."""
    rng = random.Random(0)
    out = []
    for n in lengths:
        chain = _chain(n, datetime.now(tz=UTC).isoformat(), rng)
        text = [json.dumps(e) for e in chain]
        t = time.perf_counter()
        decoded = [json.loads(x) for x in text]
        broken = verify_entries(decoded)
        took = time.perf_counter() - t
        assert broken is None
        out.append({"entries": n, "verify_seconds": round(took, 3)})
    return out


def probe_claims(conn: psycopg.Connection, jobs: int, claimers: int) -> dict[str, Any]:
    """Claim latency with ``jobs`` queued: each claimer claims and finishes
    jobs of a kind no worker runs, as the owner, until the queue is empty."""
    kind = f"load_{uuid4().hex[:8]}"
    with conn.transaction():
        with conn.cursor().copy("copy jobs (kind, payload, priority) from stdin") as cp:
            for i in range(jobs):
                cp.write_row((kind, json.dumps({"i": i}), 100))
    url = conn.info.dsn
    times: list[float] = []
    lock = threading.Lock()

    def run() -> None:
        with psycopg.connect(url, autocommit=True) as c:
            while True:
                t = time.perf_counter()
                row = c.execute(
                    "select * from vp_jobs_claim(%s, %s, %s)", ([kind], "load", 300)
                ).fetchone()
                took = time.perf_counter() - t
                if row is None or row[0] is None:
                    return
                c.execute(
                    "update jobs set state = 'succeeded' where id = %s", (row[0],)
                )
                with lock:
                    times.append(took)

    t0 = time.time()
    workers = [threading.Thread(target=run) for _ in range(claimers)]
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    took = time.time() - t0
    conn.execute("delete from jobs where kind = %s", (kind,))
    return {
        "queued": jobs,
        "claimers": claimers,
        "claims_per_second": round(len(times) / took, 1),
        **_quantiles(times),
    }


def probe_web(
    base: str,
    secrets: list[str],
    paths: list[str],
    concurrency: int,
    seconds: float,
) -> dict[str, Any]:
    """Request latency of the cached views under ``concurrency`` clients."""
    import httpx

    times: dict[str, list[float]] = {p: [] for p in paths}
    errors: dict[str, int] = {}
    lock = threading.Lock()
    stop = time.time() + seconds

    def run(i: int) -> None:
        # Without TCP_NODELAY a kept-alive client waits on delayed ACKs and
        # every request takes about 48 ms however fast the server is
        # (measured 2026-09-24; browsers set it).
        nodelay = [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]
        with httpx.Client(
            base_url=base,
            cookies={"vp_session": secrets[i % len(secrets)]},
            timeout=60,
            trust_env=False,
            transport=httpx.HTTPTransport(socket_options=nodelay),
        ) as c:
            rng = random.Random(i)
            while time.time() < stop:
                p = rng.choice(paths)
                t = time.perf_counter()
                try:
                    ok = c.get(p).status_code == 200
                except httpx.HTTPError:
                    ok = False
                took = time.perf_counter() - t
                with lock:
                    if ok:
                        times[p].append(took)
                    else:
                        errors[p] = errors.get(p, 0) + 1

    workers = [threading.Thread(target=run, args=(i,)) for i in range(concurrency)]
    t0 = time.time()
    for w in workers:
        w.start()
    for w in workers:
        w.join()
    took = time.time() - t0
    everything = [x for v in times.values() for x in v]
    return {
        "concurrency": concurrency,
        "per_second": round(len(everything) / took, 1),
        "errors": errors,
        "all": _quantiles(everything) if everything else None,
        "by_path": {p: _quantiles(v) for p, v in times.items() if v},
    }
