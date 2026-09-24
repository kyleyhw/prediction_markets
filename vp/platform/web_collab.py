"""The web routes of Phase 18: teams, sharing, comments, notifications and
leaderboards (docs/collaboration.md).

Registered by `vp.platform.web.create_app`; each route resolves its
principal with the same dependencies as the rest of the service, and the
modules it calls do the work inside a tenant session.
"""

from __future__ import annotations

import html
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field

from vp.platform import (
    auth,
    comments,
    leaderboards,
    notify,
    sharing,
    teams,
)
from vp.platform.config import Settings
from vp.platform.mail import Mailer, Message
from vp.platform.teams import NotAllowed
from vp.platform.web import (
    BrowserSession,
    CurrentPrincipal,
    Reader,
    Writer,
    _page,
)


class InviteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    role: Literal["editor", "viewer"] = "viewer"


class RoleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["owner", "editor", "viewer"]


class NameBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)


class SwitchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: UUID


class ShareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    show_pnl: bool = False
    show_spec: bool = False
    show_author: bool = False


class CommentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_kind: Literal["run", "market", "strategy"]
    subject_id: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    parent: UUID | None = None


class EditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)


class ReadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[UUID] = Field(default_factory=list, max_length=200)


class Quiet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    tz: str = Field(default="UTC", max_length=64)


class PrefsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kinds: dict[str, list[str]] = Field(default_factory=dict)
    quiet: Quiet | None = None


class OptInBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=60)


def _map(fn: Any) -> Any:
    """Run a module call, turning its refusals into HTTP answers."""
    try:
        return fn()
    except NotAllowed as exc:
        raise HTTPException(403, str(exc)) from None
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


def _share_page(snapshot: dict[str, Any], slug: str) -> str:
    esc = html.escape
    lines = "".join(f"<li>{esc(line)}</li>" for line in snapshot.get("rendering", []))
    cards = ""
    for card in snapshot.get("cards") or []:
        skill = card.get("skill")
        adv = card.get("advantage") or {}
        cards += (
            f"<h2>Backtest: {esc(str(card.get('domain') or ''))}</h2><p>"
            f"{card.get('scored', 0)} markets scored; skill against the market "
            f"{'n/a' if skill is None else f'{skill:+.3f}'}"
            + (
                f" (advantage {adv['mean']:+.4f}, 95% interval "
                f"{adv['low']:+.4f} to {adv['high']:+.4f})"
                if adv
                else ""
            )
            + ".</p>"
            + "".join(f"<p class=note>{esc(c)}</p>" for c in card.get("caveats", []))
        )
    paper = snapshot.get("paper")
    if paper:
        skill = paper.get("skill")
        cards += (
            f"<h2>Paper trading</h2><p>{paper['settled']} positions settled, "
            f"{paper['realised']:+.2f} USD of play money; skill "
            f"{'n/a' if skill is None else f'{skill:+.3f}'}.</p>"
        )
    for s in snapshot.get("standing") or []:
        rank = f"ranked {s['rank']}" if s.get("rank") else "not yet ranked"
        cards += (
            f"<p class=note>Leaderboard {esc(s['board'])}: {rank}, "
            f"{s['settled']} settled.</p>"
        )
    author = snapshot.get("author")
    fork = (
        '<form method=post action="/s/' + esc(slug) + '/fork">'
        "<button>Copy this strategy to my workspace</button></form>"
        if snapshot.get("forkable")
        else ""
    )
    return (
        f"<h1>{esc(snapshot.get('name', 'Strategy'))}</h1>"
        + (f"<p>By {esc(author)}.</p>" if author else "")
        + f"<h2>What it does</h2><ul>{lines}</ul>{cards}"
        + f"<p class=note>Published {esc(snapshot.get('published_at', ''))}. "
        "Paper trading uses play money. Past results do not predict future ones."
        f"</p>{fork}"
        + f'<p><img src="/s/{esc(slug)}/card.svg" alt="" width=300 height=100></p>'
    )


def register(
    app: FastAPI, pool: ConnectionPool, settings: Settings, mailer: Mailer
) -> None:
    # -------------------------------------------------------------- teams

    @app.get("/api/team")
    def team(principal: Reader, request: Request) -> dict[str, Any]:
        cookie = request.cookies.get(auth.SESSION_COOKIE)
        return {
            "members": teams.members(pool, principal),
            "invitations": teams.invitations(pool, principal)
            if principal.may_administer
            else [],
            "workspaces": teams.workspaces(pool, cookie) if cookie else [],
            "you_may_administer": principal.may_administer,
        }

    @app.put("/api/team", status_code=204)
    def rename_team(body: NameBody, principal: Writer) -> Response:
        _map(lambda: teams.rename(pool, principal, body.name))
        return Response(status_code=204)

    @app.post("/api/team/invitations", status_code=201)
    def invite(body: InviteBody, principal: Writer) -> dict[str, Any]:
        inv, token = _map(lambda: teams.invite(pool, principal, body.email, body.role))
        link = f"{settings.public_url}/invite?token={token}"
        mailer.send(
            Message(
                to=body.email.strip().lower(),
                subject="You are invited to a vibe-predict workspace",
                body=(
                    f"You have been invited to a vibe-predict workspace as "
                    f"{body.role}. Open this link to join; if you are not "
                    "signed in, sign in with this address first and open "
                    f"the link again. It expires in seven days.\n\n{link}\n\n"
                    "If you did not expect this, ignore this message."
                ),
            )
        )
        return {"id": inv}

    @app.delete("/api/team/invitations/{inv}", status_code=204)
    def revoke_invitation(inv: UUID, principal: Writer) -> Response:
        if not _map(lambda: teams.revoke_invitation(pool, principal, inv)):
            raise HTTPException(404, "no such invitation")
        return Response(status_code=204)

    @app.put("/api/team/members/{user_id}", status_code=204)
    def change_role(user_id: UUID, body: RoleBody, principal: Writer) -> Response:
        _map(lambda: teams.set_role(pool, principal, user_id, body.role))
        return Response(status_code=204)

    @app.delete("/api/team/members/{user_id}", status_code=204)
    def remove_member(user_id: UUID, principal: Reader) -> Response:
        _map(lambda: teams.remove(pool, principal, user_id))
        return Response(status_code=204)

    @app.post("/api/team/switch", status_code=204)
    def switch(
        body: SwitchBody, principal: BrowserSession, request: Request
    ) -> Response:
        cookie = request.cookies.get(auth.SESSION_COOKIE) or ""
        if not teams.switch(pool, cookie, body.workspace_id):
            raise HTTPException(404, "you are not a member of that workspace")
        return Response(status_code=204)

    @app.get("/api/team/activity")
    def activity(principal: Reader, limit: int = 100) -> list[dict[str, Any]]:
        return teams.activity(pool, principal, limit)

    @app.get("/invite", include_in_schema=False)
    def invite_page(principal: CurrentPrincipal, token: str = "") -> HTMLResponse:
        if not principal.attributable:
            return _page(
                "Join a workspace",
                "<h1>Join a workspace</h1><p>Sign in with the address the "
                "invitation was sent to, then open the link in the invitation "
                'again.</p><p><a href="/sign-in">Sign in</a></p>',
            )
        return _page(
            "Join a workspace",
            "<h1>Join a workspace</h1><p>You were invited to a shared "
            "workspace. Its strategies, paper accounts and runs will be "
            "visible to you, and yours there to its members.</p>"
            '<form method=post action="/invite">'
            f'<input type=hidden name=token value="{html.escape(token)}">'
            "<button>Join</button></form>",
        )

    @app.post("/invite", include_in_schema=False, response_model=None)
    def accept_invite(
        request: Request,
        principal: CurrentPrincipal,
        token: Annotated[str, Form()] = "",
    ) -> Response:
        cookie = request.cookies.get(auth.SESSION_COOKIE)
        if not principal.attributable or not cookie:
            return RedirectResponse("/sign-in", status_code=303)
        joined = teams.accept(pool, cookie, token)
        if joined is None:
            return _page(
                "Invitation",
                "<h1>That invitation cannot be used</h1><p>It may have expired, "
                "been withdrawn, or been sent to another address than the one "
                "you are signed in with.</p>",
                status=400,
            )
        return RedirectResponse("/#team", status_code=303)

    # ------------------------------------------------------------ sharing

    @app.get("/api/strategies/{strategy_id}/share")
    def get_share(strategy_id: UUID, principal: Reader) -> dict[str, Any]:
        return {"share": sharing.mine(pool, principal, strategy_id)}

    @app.put("/api/strategies/{strategy_id}/share")
    def put_share(
        strategy_id: UUID, body: ShareBody, principal: Writer
    ) -> dict[str, Any]:
        out = _map(
            lambda: sharing.publish(
                pool,
                principal,
                strategy_id,
                show_pnl=body.show_pnl,
                show_spec=body.show_spec,
                show_author=body.show_author,
            )
        )
        return {"slug": out["slug"], "url": f"{settings.public_url}/s/{out['slug']}"}

    @app.delete("/api/strategies/{strategy_id}/share", status_code=204)
    def delete_share(strategy_id: UUID, principal: Writer) -> Response:
        if not _map(lambda: sharing.revoke(pool, principal, strategy_id)):
            raise HTTPException(404, "not shared")
        return Response(status_code=204)

    @app.get("/api/public/shares/{slug}")
    def public_share(slug: str) -> dict[str, Any]:
        found = sharing.view(pool, slug)
        if found is None:
            raise HTTPException(404, "no such shared strategy")
        return found

    @app.get("/s/{slug}", include_in_schema=False)
    def share_page(slug: str) -> HTMLResponse:
        found = sharing.view(pool, slug)
        if found is None:
            return _page("Not found", "<h1>No such shared strategy</h1>", status=404)
        return _page(found.get("name", "Strategy"), _share_page(found, slug))

    @app.get("/s/{slug}/card.svg", include_in_schema=False)
    def share_card(slug: str) -> Response:
        found = sharing.view(pool, slug, count=False)
        if found is None:
            raise HTTPException(404, "no such shared strategy")
        return Response(sharing.card_svg(found), media_type="image/svg+xml")

    @app.post("/s/{slug}/fork", include_in_schema=False, response_model=None)
    def fork_page(slug: str, principal: CurrentPrincipal) -> Response:
        if not principal.attributable:
            return RedirectResponse("/sign-in", status_code=303)
        out = _map(lambda: sharing.fork(pool, principal, slug))
        return RedirectResponse(f"/#strategy/{out['strategy_id']}", status_code=303)

    @app.post("/api/public/shares/{slug}/fork", status_code=201)
    def fork(slug: str, principal: Writer) -> dict[str, Any]:
        return _map(lambda: sharing.fork(pool, principal, slug))

    # ----------------------------------------------------------- comments

    @app.get("/api/comments/{kind}/{subject_id}")
    def get_comments(
        kind: Literal["run", "market", "strategy"], subject_id: str, principal: Reader
    ) -> list[dict[str, Any]]:
        return comments.thread(pool, principal, kind, subject_id)

    @app.post("/api/comments", status_code=201)
    def post_comment(body: CommentBody, principal: Reader) -> dict[str, Any]:
        cid = _map(
            lambda: comments.add(
                pool,
                principal,
                body.subject_kind,
                body.subject_id,
                body.body,
                body.parent,
            )
        )
        return {"id": cid}

    @app.put("/api/comments/{cid}", status_code=204)
    def edit_comment(cid: UUID, body: EditBody, principal: Reader) -> Response:
        _map(lambda: comments.edit(pool, principal, cid, body.body))
        return Response(status_code=204)

    @app.delete("/api/comments/{cid}", status_code=204)
    def delete_comment(cid: UUID, principal: Reader) -> Response:
        _map(lambda: comments.delete(pool, principal, cid))
        return Response(status_code=204)

    @app.post("/api/comments/{cid}/hide", status_code=204)
    def hide_comment(cid: UUID, principal: Reader) -> Response:
        _map(lambda: comments.hide(pool, principal, cid))
        return Response(status_code=204)

    # ------------------------------------------------------- notifications

    @app.get("/api/notifications")
    def get_notifications(principal: Reader) -> dict[str, Any]:
        return notify.listing(pool, principal)

    @app.post("/api/notifications/read")
    def read_notifications(body: ReadBody, principal: Reader) -> dict[str, int]:
        return {"marked": notify.mark_read(pool, principal, body.ids)}

    @app.get("/api/notifications/prefs")
    def get_prefs(principal: Reader) -> dict[str, Any]:
        return notify.get_prefs(pool, principal)

    @app.put("/api/notifications/prefs")
    def put_prefs(body: PrefsBody, principal: Reader) -> dict[str, Any]:
        prefs = body.model_dump()
        return _map(lambda: notify.set_prefs(pool, principal, prefs))

    # -------------------------------------------------------- leaderboards

    @app.get("/api/leaderboards")
    def get_leaderboards(principal: Reader) -> dict[str, Any]:
        return leaderboards.read(pool)

    @app.put("/api/strategies/{strategy_id}/leaderboard", status_code=204)
    def join_board(strategy_id: UUID, body: OptInBody, principal: Writer) -> Response:
        _map(
            lambda: leaderboards.opt_in(pool, principal, strategy_id, body.display_name)
        )
        return Response(status_code=204)

    @app.delete("/api/strategies/{strategy_id}/leaderboard", status_code=204)
    def leave_board(strategy_id: UUID, principal: Writer) -> Response:
        if not _map(lambda: leaderboards.opt_out(pool, principal, strategy_id)):
            raise HTTPException(404, "not entered")
        return Response(status_code=204)
