"""The web service: sign-in, the principal on every request, and the views.

One FastAPI application over the unchanged engine. What it adds to the
engine is who is asking and whether they may: every request resolves to a
`Principal` from a session cookie or a bearer token, and every route that
reads anything requires one that names a person.

Five rules, each enforced here rather than left to the routes:

* **The service connects only as `vp_app`.** At start it checks that its
  database role is neither a superuser nor able to bypass row-level
  security, and does not own the tables, and refuses to start otherwise.
  The tenancy tests prove isolation for exactly that role, so running as
  any other would make them prove nothing.
* **State changes must come from our own pages.** A request that changes
  anything and is not bearer-authenticated must carry
  `Sec-Fetch-Site: same-origin` or an `Origin` of this service; otherwise
  it is refused. A
  browser sends the session cookie with a cross-site form post, so without
  this check another site could sign a visitor out, or into an account of
  the attacker's choosing. Bearer requests are exempt because browsers
  never attach that header by themselves.
* **Opening a sign-in link does not sign in.** `GET /auth/verify` shows a
  page with one button; only the `POST` it makes consumes the token. Mail
  scanners and link previews fetch every URL in a message, and a link that
  signed in on `GET` would be spent before the person clicked it.
* **Secrets stay out of logs and referrers.** The access log is filtered so
  a `token=` value never reaches it, and every response carries
  `Referrer-Policy: same-origin`, so the sign-in page's URL, token and all,
  is never sent to another site. Not `no-referrer`: under that policy a
  browser sends `Origin: null` even on our own form posts, which the
  cross-site check above would then refuse; a real browser run found it.
* **Nothing personal is cached by the browser.** Every response except the
  fonts carries `Cache-Control: no-store`. Without it, Chromium served the
  dashboard from its cache after sign-out without asking the server; the
  data calls were refused, but the page was not, which on a shared
  computer is the wrong thing to show. Also found by the browser run.

The dashboard's JSON endpoints are the ones `vp ui` serves, backed by the
same `DataView` over the data root, now behind sign-in. That data root is
shared by everyone on this service until per-workspace storage lands (plan,
tasks 30 and 37); on a development machine with one person that is
harmless, and it is recorded in `docs/platform.md`.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

from vp.domains import DOMAINS
from vp.platform import auth
from vp.platform.config import Settings
from vp.platform.db import tenant_session
from vp.platform.mail import Mailer, Message, OutboxMailer
from vp.platform.principal import AuthMethod, Principal
from vp.ui.server import STATIC, DataView

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}
_STAMP = re.compile(r"^[0-9A-Za-z_-]{1,64}$")
_FIGURE = re.compile(r"^[a-z_]{1,64}\.png$")
_SECRET_QUERY = re.compile(r"([?&]token=)[^&\s\"']+")


class DatabaseRoleError(RuntimeError):
    """The service's database role is one row-level security does not bind."""


def check_database(conn: psycopg.Connection) -> None:
    """Refuse to serve unless connected as a role the policies apply to.

    Raises:
        DatabaseRoleError: the role is a superuser, may bypass row-level
            security, owns the tables, or the schema is not migrated.
    """
    row = conn.execute(
        "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
    ).fetchone()
    if row is None or row[0] or row[1]:
        raise DatabaseRoleError(
            "VP_DATABASE_URL connects as a superuser or a role that bypasses "
            "row-level security; the service must connect as vp_app"
        )
    owns = conn.execute(
        "select exists (select 1 from pg_tables where schemaname = 'public' "
        "and tablename = 'workspaces' and tableowner = current_user)"
    ).fetchone()
    if owns and owns[0]:
        raise DatabaseRoleError(
            "VP_DATABASE_URL connects as the owner of the tables, which "
            "row-level security does not bind; connect as vp_app"
        )
    ready = conn.execute(
        "select to_regprocedure('vp_auth_sign_in(text, text)') is not null"
    ).fetchone()
    if not ready or not ready[0]:
        raise DatabaseRoleError("the schema is not migrated; run: vp db migrate")


def same_origin(
    origin: str | None, host: str | None, public_url: str, fetch_site: str | None
) -> bool:
    """Whether a state-changing browser request came from this service.

    `Sec-Fetch-Site: same-origin` is enough on its own: browsers set it and
    a page cannot. Otherwise a real `Origin` must be the configured public
    origin or name the host the request was sent to. The literal `null`
    origin never passes by itself, since sandboxed frames and some
    redirects send it; a browser whose referrer policy suppresses the
    origin still sends the fetch metadata, which is why that comes first.
    """
    if fetch_site == "same-origin":
        return True
    if not origin or origin == "null":
        return False
    public = urlsplit(public_url)
    if origin.rstrip("/") == f"{public.scheme}://{public.netloc}":
        return True
    return bool(host) and urlsplit(origin).netloc == host


def redact(text: str) -> str:
    """Replace any `token=` query value with a placeholder."""
    return _SECRET_QUERY.sub(r"\1[redacted]", text)


class RedactSecrets(logging.Filter):
    """Strip `token=` values from log records, keeping their argument shape.

    uvicorn's access formatter unpacks `record.args` positionally, so the
    arguments are redacted in place rather than folded into the message.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact(a) if isinstance(a, str) else a for a in record.args
            )
        return True


def install_log_redaction() -> None:
    """Attach the filter to the server's loggers."""
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(RedactSecrets())


class TokenRequest(BaseModel):
    """A request to create an API token."""

    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    scope: Literal["read", "write"] = "read"


# ---------------------------------------------------------------- principal
#
# At module level, not inside `create_app`: FastAPI resolves the string
# annotations `from __future__ import annotations` produces against the
# module's globals, so a dependency alias defined in a function body would
# be read as a query parameter instead.


def current_principal(request: Request) -> Principal:
    """The principal behind a request: bearer token, session cookie, or none.

    A bearer header that does not resolve is refused outright rather than
    falling back to the cookie, so a broken token is noticed.
    """
    pool: ConnectionPool = request.app.state.pool
    header = request.headers.get("authorization", "")
    if header[:7].lower() == "bearer ":
        with pool.connection() as conn:
            principal = auth.resolve_api_token(conn, header[7:].strip())
        if principal is None:
            raise HTTPException(
                401, "invalid or revoked token", headers={"WWW-Authenticate": "Bearer"}
            )
        return principal
    cookie = request.cookies.get(auth.SESSION_COOKIE)
    if cookie:
        with pool.connection() as conn:
            principal = auth.resolve_session(conn, cookie)
        if principal is not None:
            return principal
    return Principal.anonymous()


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def reader(principal: CurrentPrincipal) -> Principal:
    """A principal that names a person and may read its workspace."""
    if not principal.attributable:
        raise HTTPException(401, "sign in first")
    if not principal.may_read:
        raise HTTPException(403, "no access to this workspace")
    return principal


Reader = Annotated[Principal, Depends(reader)]


def browser_session(principal: Reader) -> Principal:
    """A reader signed in through the browser, not a token."""
    if principal.auth_method is not AuthMethod.SESSION:
        raise HTTPException(403, "tokens are managed from a signed-in browser session")
    return principal


BrowserSession = Annotated[Principal, Depends(browser_session)]


def create_app(
    settings: Settings,
    *,
    mailer: Mailer | None = None,
    pool: ConnectionPool | None = None,
) -> FastAPI:
    """Build the application.

    Args:
        settings: the loaded settings.
        mailer: where sign-in emails go; the development outbox by default.
        pool: a connection pool, for tests; built from the settings by
            default and opened when the application starts.
    """
    pool = pool or ConnectionPool(
        settings.database_url,
        kwargs={"autocommit": True},
        min_size=1,
        max_size=10,
        open=False,
    )
    mailer = mailer or OutboxMailer(settings.outbox_dir)
    view = DataView(settings.data_root)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        pool.open(wait=True, timeout=10)
        try:
            with pool.connection() as conn:
                check_database(conn)
            yield
        finally:
            pool.close()

    app = FastAPI(
        title="vibe-predict",
        summary="Build, score and paper trade prediction-market strategies.",
        lifespan=lifespan,
    )
    app.state.pool = pool

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        bearer = request.headers.get("authorization", "")[:7].lower() == "bearer "
        if (
            request.method not in _SAFE_METHODS
            and not bearer
            and not same_origin(
                request.headers.get("origin"),
                request.headers.get("host"),
                settings.public_url,
                request.headers.get("sec-fetch-site"),
            )
        ):
            return JSONResponse(
                {"detail": "cross-site request refused"}, status_code=403
            )
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        # Nothing but the fonts may sit in a browser's cache: pages and data
        # are per person, and a cached page outlives signing out.
        if not request.url.path.startswith("/fonts/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse({"detail": "internal error"}, status_code=500)

    # --------------------------------------------------------------- health

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        """The process is up."""
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:
        """The process can reach its database."""
        try:
            with pool.connection(timeout=2) as conn:
                conn.execute("select 1")
        except Exception:  # noqa: BLE001 - any failure means not ready
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return JSONResponse({"status": "ready"})

    # -------------------------------------------------------------- sign-in

    @app.get("/sign-in", include_in_schema=False, response_model=None)
    def sign_in_page(principal: CurrentPrincipal) -> Response:
        if principal.attributable:
            return RedirectResponse("/", status_code=303)
        return _page("Sign in", _sign_in_form())

    @app.post("/auth/sign-in", include_in_schema=False)
    def request_link(email: Annotated[str, Form()] = "") -> HTMLResponse:
        """Send a sign-in link. Answers the same whether or not one was sent."""
        address = auth.normalize_email(email)
        if address is None:
            return _page(
                "Sign in",
                _sign_in_form("That does not look like an email address."),
                status=422,
            )
        with pool.connection() as conn:
            token = auth.request_sign_in(conn, address)
        if token is not None:
            link = f"{settings.public_url}/auth/verify?token={token}"
            mailer.send(
                Message(
                    to=address,
                    subject="Your vibe-predict sign-in link",
                    body=(
                        "Open this link to sign in to vibe-predict. It works "
                        f"once and expires in 15 minutes.\n\n{link}\n\n"
                        "If you did not ask for it, ignore this message."
                    ),
                )
            )
        note = (
            "<p class=note>Development: the link is written to "
            f"<code>{html.escape(str(settings.outbox_dir))}</code>.</p>"
            if isinstance(mailer, OutboxMailer) and mailer.directory
            else ""
        )
        return _page(
            "Check your email",
            "<h1>Check your email</h1><p>If that address can sign in, a link "
            "is on its way. It works once and expires in 15 minutes.</p>" + note,
        )

    @app.get("/auth/verify", include_in_schema=False)
    def confirm(token: str = "") -> HTMLResponse:
        """A button, not a sign-in: link scanners must not spend the token."""
        return _page(
            "Sign in",
            "<h1>Sign in to vibe-predict</h1>"
            '<form method="post" action="/auth/verify">'
            f'<input type="hidden" name="token" value="{html.escape(token)}">'
            "<button type=submit>Sign in</button></form>",
        )

    @app.post("/auth/verify", include_in_schema=False, response_model=None)
    def verify(token: Annotated[str, Form()] = "") -> Response:
        with pool.connection() as conn:
            result = auth.sign_in(conn, token) if token else None
        if result is None:
            return _page(
                "Link expired",
                "<h1>That link has expired</h1><p>Sign-in links work once and "
                'for 15 minutes. <a href="/sign-in">Ask for a new one</a>.</p>',
                status=400,
            )
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            auth.SESSION_COOKIE,
            result.session,
            max_age=auth.SESSION_SECONDS,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookies,
            path="/",
        )
        return response

    @app.post("/auth/sign-out", include_in_schema=False)
    def sign_out(request: Request) -> RedirectResponse:
        cookie = request.cookies.get(auth.SESSION_COOKIE)
        if cookie:
            with pool.connection() as conn:
                auth.end_session(conn, cookie)
        response = RedirectResponse("/sign-in", status_code=303)
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response

    @app.get("/auth/me")
    def me(principal: Reader) -> dict[str, Any]:
        """Who is signed in, and in which workspace."""
        with pool.connection() as conn, tenant_session(conn, principal):
            user = conn.execute("select email from users").fetchone()
            workspace = conn.execute("select id, name from workspaces").fetchone()
        return {
            "email": user[0] if user else None,
            "workspace": {"id": workspace[0], "name": workspace[1]}
            if workspace
            else None,
            "roles": sorted(principal.roles),
            "auth_method": principal.auth_method,
        }

    # ---------------------------------------------------------- API tokens

    @app.post("/api/tokens", status_code=201)
    def create_token(body: TokenRequest, principal: BrowserSession) -> dict[str, Any]:
        """Create an API token. The secret is in this response and nowhere else."""
        if body.scope == "write" and not principal.may_write:
            raise HTTPException(403, "your role cannot hold a write token")
        with pool.connection() as conn, tenant_session(conn, principal):
            secret, record = auth.create_api_token(
                conn, principal, body.name.strip(), body.scope
            )
        return {"token": secret, **_token_json(record)}

    @app.get("/api/tokens")
    def list_tokens(principal: BrowserSession) -> list[dict[str, Any]]:
        """Your tokens in this workspace, without their secrets."""
        with pool.connection() as conn, tenant_session(conn, principal):
            return [_token_json(t) for t in auth.list_api_tokens(conn)]

    @app.delete("/api/tokens/{token_id}", status_code=204)
    def revoke_token(token_id: UUID, principal: BrowserSession) -> Response:
        """Revoke one of your tokens."""
        with pool.connection() as conn, tenant_session(conn, principal):
            revoked = auth.revoke_api_token(conn, token_id)
        if not revoked:
            raise HTTPException(404, "no such token")
        return Response(status_code=204)

    # ----------------------------------------------------------- dashboard

    @app.get("/api/overview")
    def overview(principal: Reader) -> Any:
        """Per-domain counts and the paper accounts."""
        return view.overview()

    @app.get("/api/backtests")
    def backtests(principal: Reader) -> Any:
        """Every backtest run with its tables."""
        return view.backtests()

    @app.get("/api/backtests/{domain}/{stamp}/{figure}")
    def figure(domain: str, stamp: str, figure: str, principal: Reader) -> FileResponse:
        """One figure of one backtest run."""
        if (
            domain not in DOMAINS
            or not _STAMP.match(stamp)
            or not _FIGURE.match(figure)
        ):
            raise HTTPException(404, "no such figure")
        base = (settings.data_root / "backtests").resolve()
        path = (base / domain / stamp / figure).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise HTTPException(404, "no such figure")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/paper")
    def paper(
        principal: Reader, limit: Annotated[int, Query(ge=1, le=1000)] = 50
    ) -> Any:
        """The paper ledger: integrity, accounts, positions, settlements."""
        return view.paper(limit=limit)

    @app.get("/api/snapshots/{domain}")
    def snapshot(domain: str, principal: Reader) -> Any:
        """The latest snapshot of a domain's open markets."""
        if domain not in DOMAINS:
            raise HTTPException(404, "no such domain")
        return view.snapshot(domain)

    @app.get("/api/forecasts")
    def forecasts(
        principal: Reader, limit: Annotated[int, Query(ge=1, le=1000)] = 100
    ) -> Any:
        """The most recent paper forecasts."""
        return view.forecasts(limit=limit)

    # ---------------------------------------------------------------- page

    app.mount("/fonts", StaticFiles(directory=STATIC / "fonts"), name="fonts")

    @app.get("/", include_in_schema=False, response_model=None)
    def index(principal: CurrentPrincipal) -> Response:
        if not principal.attributable:
            return RedirectResponse("/sign-in", status_code=303)
        return FileResponse(STATIC / "index.html", media_type="text/html")

    return app


def _token_json(token: auth.ApiToken) -> dict[str, Any]:
    return {
        "id": token.id,
        "name": token.name,
        "scope": token.scope,
        "created_at": token.created_at,
        "revoked_at": token.revoked_at,
    }


def _sign_in_form(error: str = "") -> str:
    message = f"<p class=error role=alert>{html.escape(error)}</p>" if error else ""
    return (
        "<h1>Sign in</h1><p>Enter your email and we will send you a link. "
        "There is no password.</p>" + message + '<form method="post" '
        'action="/auth/sign-in"><label for=email>Email</label>'
        "<input id=email name=email type=email autocomplete=email required "
        "autofocus><button type=submit>Send me a link</button></form>"
    )


_STYLE = """
@font-face { font-family: "Instrument Sans";
  src: url(/fonts/InstrumentSans-latin.woff2) format("woff2");
  font-weight: 400 700; font-display: swap; }
:root { color-scheme: light dark; --plane: #f9f9f7; --surface: #fcfcfb;
  --ink: #0b0b0b; --ink-2: #52514e; --ring: rgba(11,11,11,.10);
  --accent: #2a78d6; --bad: #d03b3b; }
@media (prefers-color-scheme: dark) { :root { --plane: #0d0d0d;
  --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
  --ring: rgba(255,255,255,.10); --accent: #3987e5; --bad: #e66767; } }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center;
  background: var(--plane); color: var(--ink); padding: 16px;
  font: 16px/1.55 "Instrument Sans", system-ui, sans-serif; }
main { width: 100%; max-width: 400px; background: var(--surface);
  border: 1px solid var(--ring); border-radius: 12px; padding: 28px; }
.brand { font-weight: 600; font-size: 14px; color: var(--ink-2);
  margin-bottom: 18px; }
h1 { font-size: 22px; margin: 0 0 8px; }
p { color: var(--ink-2); margin: 0 0 16px; }
label { display: block; font-weight: 500; margin-bottom: 6px; }
input { width: 100%; font: inherit; padding: 10px 12px; border-radius: 8px;
  border: 1px solid var(--ring); background: var(--plane); color: var(--ink);
  margin-bottom: 14px; }
button { width: 100%; font: inherit; font-weight: 600; padding: 10px 12px;
  border: 0; border-radius: 8px; background: var(--accent); color: #fff;
  cursor: pointer; }
button:focus-visible, input:focus-visible, a:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px; }
a { color: var(--accent); }
.error { color: var(--bad); }
.note { font-size: 13px; }
code { font-size: 12px; word-break: break-all; }
"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width, initial-scale=1">'
        f"<title>{html.escape(title)} · vibe-predict</title>"
        f"<style>{_STYLE}</style></head><body><main>"
        f"<div class=brand>vibe-predict</div>{body}</main></body></html>",
        status_code=status,
    )
