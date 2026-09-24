"""The shadow forecaster's routes (docs/shadow.md, Phase 19)."""

from __future__ import annotations

import csv
import io
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field

from vp.platform import shadow
from vp.platform.web import BrowserSession, Reader, Writer


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: str = Field(min_length=42, max_length=42)
    consent: bool


class SignatureBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signature: str = Field(min_length=130, max_length=132)


class TryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str = Field(min_length=1, max_length=40)
    index: int = Field(ge=0, le=10)


def register(app: FastAPI, pool: ConnectionPool) -> None:
    @app.get("/api/shadow")
    def imports(principal: Reader) -> dict[str, Any]:
        return {
            "imports": shadow.listing(pool, principal),
            "consent": shadow.CONSENT,
            "consent_version": shadow.CONSENT_VERSION,
        }

    @app.post("/api/shadow", status_code=202)
    def start(body: ImportBody, principal: Writer) -> dict[str, Any]:
        if not body.consent:
            raise HTTPException(409, "linking an address needs your consent")
        try:
            return shadow.start(pool, principal, body.address)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/shadow/{iid}")
    def one(iid: UUID, principal: Reader) -> dict[str, Any]:
        found = shadow.get(pool, principal, iid)
        if found is None:
            raise HTTPException(404, "no such import")
        return found

    @app.delete("/api/shadow/{iid}", status_code=204)
    def remove(iid: UUID, principal: Reader) -> Response:
        if not shadow.delete(pool, principal, iid):
            raise HTTPException(404, "no such import")
        return Response(status_code=204)

    @app.post("/api/shadow/{iid}/verify")
    def verify(
        iid: UUID, body: SignatureBody, principal: BrowserSession
    ) -> dict[str, bool]:
        from vp.venues.polymarket import fetch_profile

        try:
            return {
                "verified": shadow.verify(
                    pool, principal, iid, body.signature, fetch_profile
                )
            }
        except LookupError:
            raise HTTPException(404, "no such import") from None

    @app.post("/api/shadow/{iid}/try", status_code=201)
    def try_rule(iid: UUID, body: TryBody, principal: Writer) -> dict[str, str]:
        try:
            convo = shadow.try_rule(pool, principal, iid, body.domain, body.index)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return {"conversation_id": convo}

    @app.get("/api/shadow/{iid}/card.csv")
    def export_csv(iid: UUID, principal: Reader) -> Response:
        from vp.shadow.card import csv_rows

        found = shadow.get(pool, principal, iid)
        if found is None or not found.get("card"):
            raise HTTPException(404, "no card yet")
        out = io.StringIO()
        csv.writer(out).writerows(csv_rows(found["card"]))
        return Response(
            out.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="report-card.csv"'},
        )
