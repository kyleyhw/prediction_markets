"""Risk, strategy health and promotion routes (docs/portfolio.md, Phase 20)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict

from vp.platform import portfolio
from vp.platform.db import tenant_session
from vp.platform.storage import ObjectStore, SharedRoot
from vp.platform.teams import NotAllowed
from vp.platform.web import BrowserSession, Reader, Writer


class PromotionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: Literal["paper", "live"]


def register(
    app: FastAPI, pool: ConnectionPool, shared: SharedRoot, store: ObjectStore
) -> None:
    def newest(principal: Any, strategy: UUID) -> UUID:
        with pool.connection() as conn, tenant_session(conn, principal):
            row = conn.execute(
                "select id from strategy_versions where strategy_id = %s "
                "order by version desc limit 1",
                (strategy,),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "no such strategy")
        return row[0]

    @app.get("/api/risk")
    def risk(principal: Reader) -> dict[str, Any]:
        return portfolio.risk(pool, principal, shared.root, store)

    @app.get("/api/strategies/{strategy_id}/health")
    def health(strategy_id: UUID, principal: Reader) -> dict[str, Any]:
        return {"health": portfolio.get_health(pool, principal, strategy_id)}

    @app.post("/api/strategies/{strategy_id}/health/resume")
    def resume(strategy_id: UUID, principal: BrowserSession) -> dict[str, bool]:
        try:
            return {"resumed": portfolio.resume(pool, principal, strategy_id)}
        except NotAllowed as exc:
            raise HTTPException(403, str(exc)) from None

    @app.get("/api/strategies/{strategy_id}/promotion")
    def evaluations(strategy_id: UUID, principal: Reader) -> dict[str, Any]:
        return {"evaluations": portfolio.evaluations(pool, principal, strategy_id)}

    @app.post("/api/strategies/{strategy_id}/promotion", status_code=201)
    def evaluate(
        strategy_id: UUID, body: PromotionBody, principal: Writer
    ) -> dict[str, Any]:
        version = newest(principal, strategy_id)
        return portfolio.evaluate(
            pool, principal, version, body.target, shared.root, store
        )

    @app.post("/api/promotions/{evaluation_id}/approve", status_code=204)
    def approve(evaluation_id: UUID, principal: BrowserSession) -> None:
        """Approving is a person's act on the page, never a token's or a model's."""
        try:
            portfolio.approve(pool, principal, evaluation_id)
        except NotAllowed as exc:
            raise HTTPException(403, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
