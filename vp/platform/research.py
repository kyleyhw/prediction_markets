"""The research assistant on the platform (plan, task 54).

The engine's tools (`vp.strategy.agent.ToolBox`) over the shared data,
plus the person's own strategies: what they are, their run cards and paper
records, a comparison of two runs, and starting a backtest. A backtest the
assistant starts must cost nothing (a belief without a model); one that
would spend money is left for the person to start from the strategy page,
where the estimate is shown first. Every read runs as the person, in their
workspace.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from psycopg_pool import ConnectionPool

from vp.platform import jobs, strategies
from vp.platform.db import tenant_session
from vp.platform.principal import Principal
from vp.strategy.agent import ToolBox, ToolError, tool_schema
from vp.strategy.card import manifest_diff
from vp.strategy.spec import uses_model

#: What a research message holds against the budget until its cost is known.
RESEARCH_RESERVE_USD = 0.60


class PlatformToolBox(ToolBox):
    """The research tools for one person in one workspace."""

    def __init__(
        self, root: Any, pool: ConnectionPool, principal: Principal, **kwargs: Any
    ) -> None:
        super().__init__(root, **kwargs)
        self.pool = pool
        self.principal = principal

    def definitions(self) -> list[dict[str, Any]]:
        uuid = {"type": "string", "format": "uuid"}
        return super().definitions() + [
            tool_schema(
                "my_strategies",
                "The person's own strategies: name, status, version, and what "
                "each runs in plain words.",
                {},
            ),
            tool_schema(
                "strategy_results",
                "One strategy in full: its versions, its backtest run cards "
                "(scores against the market, bets, fees, caveats) and its paper "
                "accounts.",
                {"strategy_id": uuid},
            ),
            tool_schema(
                "compare_runs",
                "Two backtest runs side by side: their cards and what differs in "
                "what produced them.",
                {"run_a": uuid, "run_b": uuid},
            ),
            tool_schema(
                "start_backtest",
                "Queue a backtest of a strategy's newest version. Only for a "
                "strategy whose belief uses no AI model; it runs in the background.",
                {"strategy_id": uuid},
            ),
            tool_schema(
                "propose_brief",
                "Propose a scheduled brief: template disagreements (variables "
                "threshold in points, domains), settlements (days) or weekly; a "
                "five-field cron schedule and an IANA timezone. It is saved "
                "switched off: the person switches it on under Briefs if they "
                "want it. Never say it is scheduled.",
                {
                    "template": {
                        "type": "string",
                        "enum": ["disagreements", "settlements", "weekly"],
                    },
                    "variables_json": {"type": "string"},
                    "cron": {"type": "string"},
                    "timezone": {"type": "string"},
                },
            ),
        ]

    def _uuid(self, value: str) -> UUID:
        try:
            return UUID(value)
        except ValueError:
            raise ToolError(f"{value!r} is not an id") from None

    def tool_my_strategies(self) -> str:
        rows = strategies.listing(self.pool, self.principal)
        if not rows:
            return "The person has no strategies yet."
        return "\n".join(
            f"{r['id']} | {r['name']} | {r['status']} | version {r['version']} | "
            + " ".join(r["rendering"])
            for r in rows
        )

    def tool_strategy_results(self, strategy_id: str) -> str:
        try:
            found = strategies.detail(
                self.pool, self.principal, self._uuid(strategy_id)
            )
        except strategies.NotFound:
            raise ToolError("no such strategy in this workspace") from None
        for run in found["runs"]:
            run["card"] = (run.pop("results") or {}).get("card")
        return json.dumps(found, default=str)

    def _run(self, run_id: str) -> dict[str, Any]:
        with self.pool.connection() as conn, tenant_session(conn, self.principal):
            row = conn.execute(
                "select results, manifest from runs where id = %s",
                (self._uuid(run_id),),
            ).fetchone()
        if row is None:
            raise ToolError(f"no run {run_id} in this workspace")
        return {"card": (row[0] or {}).get("card"), "manifest": row[1] or {}}

    def tool_compare_runs(self, run_a: str, run_b: str) -> str:
        a, b = self._run(run_a), self._run(run_b)
        return json.dumps(
            {
                "a": a["card"],
                "b": b["card"],
                "what_differs": manifest_diff(a["manifest"], b["manifest"]),
            },
            default=str,
        )

    def tool_start_backtest(self, strategy_id: str) -> str:
        try:
            head = strategies.latest(self.pool, self.principal, self._uuid(strategy_id))
        except strategies.NotFound:
            raise ToolError("no such strategy in this workspace") from None
        spec = head["spec"]
        if uses_model(spec):
            raise ToolError(
                "this backtest would spend money on the AI model; the person "
                "starts it from the strategy page, where its cost is shown first"
            )
        job = jobs.enqueue(
            self.pool,
            self.principal,
            "backtest",
            {"strategy_version_id": str(head["version_id"])},
        )
        return f"queued backtest job {job} for version {head['version']}"

    def tool_propose_brief(
        self, template: str, variables_json: str, cron: str, timezone: str
    ) -> str:
        from vp.platform import briefs

        try:
            variables = json.loads(variables_json or "{}")
            brief = briefs.propose(
                self.pool,
                self.principal,
                template,
                variables,
                cron,
                timezone,
                None,
                proposed_by="assistant",
            )
        except (ValueError, KeyError) as exc:
            raise ToolError(str(exc)) from None
        return (
            f"proposed brief {brief}; it is off until the person switches it on "
            "under Briefs"
        )


def history(convo: dict[str, Any]) -> tuple[list[tuple[str, str]], int, int]:
    """A research conversation's turns as ``(role, text)``, with the tokens
    and turns it has used."""
    out: list[tuple[str, str]] = []
    tokens = turns = 0
    for turn in convo["turns"]:
        content = turn["content"]
        if turn["role"] == "user":
            out.append(("user", content["words"]))
            turns += 1
        else:
            out.append(("assistant", content.get("text") or content.get("message", "")))
            tokens += content.get("input_tokens", 0) + content.get("output_tokens", 0)
    return out, tokens, turns
