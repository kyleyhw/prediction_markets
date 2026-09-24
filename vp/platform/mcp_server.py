"""A read-only MCP server for other agents (plan, task 88;
docs/collaboration.md).

Mounted at ``/mcp`` over streamable HTTP with the official SDK. A caller
presents one of its own API tokens as a bearer token; every tool resolves
that token to the person and workspace it belongs to and reads only there.
The tools read markets, evidence at a cutoff, forecasts, run cards, paper
status and the signal bench. No tool can place, sign or send anything, and
none ever will: `TOOLS` is the whole list, and a test holds it to the
read-only allow-list.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from psycopg_pool import ConnectionPool
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

from vp.platform import auth
from vp.platform.db import tenant_session
from vp.platform.principal import Principal
from vp.strategy.agent import ToolBox, ToolError

TOOLS = (
    "search_markets",
    "market_detail",
    "evidence",
    "forecasts",
    "run_cards",
    "paper_status",
    "signal_bench",
)

INSTRUCTIONS = (
    "Read-only access to one vibe-predict workspace: prediction markets, "
    "evidence as it stood before a cutoff, the workspace's forecasts, backtest "
    "run cards, paper-trading status (play money) and the signal bench. "
    "Nothing here can place or change anything."
)


class Unauthorised(PermissionError):
    pass


def _principal(pool: ConnectionPool, headers: Any) -> Principal:
    header = (headers or {}).get("authorization", "")
    if header[:7].lower() != "bearer ":
        raise Unauthorised("present an API token as a bearer token")
    with pool.connection() as conn:
        found = auth.resolve_api_token(conn, header[7:].strip())
    if found is None or not found.may_read:
        raise Unauthorised("that token is invalid or revoked")
    return found


def build(
    pool: ConnectionPool,
    root: Callable[[], Any],
    public_url: str,
) -> tuple[MCPServer, ASGIApp, Starlette]:
    """The server, its ASGI app refusing requests without a live token, and
    the SDK's own app, whose lifespan the service runs.

    ``root`` returns the shared data root, brought up to date.
    """
    server = MCPServer("vibe-predict", instructions=INSTRUCTIONS)

    def who(ctx: Context) -> Principal:
        return _principal(pool, ctx.headers)

    def tools() -> ToolBox:
        return ToolBox(root())

    def answer(fn: Callable[[], str]) -> str:
        try:
            return fn()
        except ToolError as exc:
            return f"error: {exc}"

    @server.tool()
    def search_markets(
        domain: str, words: str, ctx: Context, open_now: bool = True, limit: int = 20
    ) -> str:
        """Markets in a domain whose question contains the words: open now with
        prices, or settled with the outcome."""
        who(ctx)
        return answer(
            lambda: tools().tool_search_markets(domain, words, open_now, min(limit, 50))
        )

    @server.tool()
    def market_detail(domain: str, market_id: str, ctx: Context) -> str:
        """One market in full: question, outcomes, parsed fields, price, fee,
        end date, outcome if settled, and its resolution rules."""
        who(ctx)
        return answer(lambda: tools().tool_explain_market(domain, market_id))

    @server.tool()
    def evidence(domain: str, subject: str, cutoff: str, ctx: Context) -> str:
        """What was known before a cutoff date (YYYY-MM-DD): a team's settled
        results, or a city's daily highs."""
        who(ctx)
        return answer(lambda: tools().tool_evidence(domain, subject, cutoff))

    @server.tool()
    def forecasts(ctx: Context, limit: int = 50) -> str:
        """The workspace's newest forecasts: forecaster, market, probability,
        cutoff."""
        principal = who(ctx)
        with pool.connection() as conn, tenant_session(conn, principal):
            rows = conn.execute(
                "select forecaster, market_id, domain, p_hat, cutoff from forecasts "
                "order by at desc limit %s",
                (min(max(limit, 1), 200),),
            ).fetchall()
        return json.dumps(
            [
                {"forecaster": f, "market_id": m, "domain": d, "p": p, "cutoff": c}
                for f, m, d, p, c in rows
            ],
            default=str,
        )

    @server.tool()
    def run_cards(ctx: Context, limit: int = 10) -> str:
        """The workspace's newest backtest run cards: scores against the market,
        bets, fees and caveats."""
        principal = who(ctx)
        with pool.connection() as conn, tenant_session(conn, principal):
            rows = conn.execute(
                "select id, config ->> 'domain', results -> 'card', created_at "
                "from runs where results ? 'card' order by created_at desc limit %s",
                (min(max(limit, 1), 50),),
            ).fetchall()
        return json.dumps(
            [{"run_id": r, "domain": d, "card": c, "at": a} for r, d, c, a in rows],
            default=str,
        )

    @server.tool()
    def paper_status(ctx: Context) -> str:
        """Each paper account (play money): positions open and settled, and
        realised profit or loss."""
        principal = who(ctx)
        with pool.connection() as conn, tenant_session(conn, principal):
            rows = conn.execute(
                "select a.name, "
                "count(*) filter (where e.kind = 'order'), "
                "count(*) filter (where e.kind = 'settlement'), "
                "coalesce(sum((e.entry -> 'data' ->> 'pnl')::float) "
                "filter (where e.kind = 'settlement'), 0) "
                "from paper_accounts a left join ledger_entries e "
                "on e.account_id = a.id group by a.name order by a.name"
            ).fetchall()
        return json.dumps(
            [
                {
                    "account": n,
                    "orders": o,
                    "settled": s,
                    "open": o - s,
                    "realised_usd": round(p, 2),
                }
                for n, o, s, p in rows
            ]
        )

    @server.tool()
    def signal_bench(domain: str, ctx: Context) -> str:
        """The latest bench of every signal against the market on a domain."""
        from vp.platform.signals import latest_bench

        who(ctx)
        return json.dumps(latest_bench(pool).get(domain) or {}, default=str)

    host = urlparse(public_url).netloc
    app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host, host.split(":")[0] + ":*"],
            allowed_origins=[public_url],
        ),
    )

    async def guarded(scope: Scope, receive: Receive, send: Send) -> None:
        """Refuse a request without a live token before the SDK sees it."""
        if scope["type"] == "http":
            headers = {
                k.decode().lower(): v.decode() for k, v in scope.get("headers") or []
            }
            try:
                _principal(pool, headers)
            except Unauthorised as exc:
                await _refuse(send, str(exc))
                return
        await app(scope, receive, send)

    return server, guarded, app


async def _refuse(send: Callable[[dict], Awaitable[None]], why: str) -> None:
    body = json.dumps({"detail": why}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
