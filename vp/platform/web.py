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
* **The page runs only its own scripts.** Every page but the OpenAPI
  reference carries a Content-Security-Policy allowing scripts from this
  origin alone, with no inline script, so text from a market question or a
  ledger entry that slipped past escaping still could not run.
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

import hmac
import html
import json
import logging
import re
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
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
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from vp.domains import DOMAINS
from vp.domains.pack import PACKS
from vp.platform import audit, auth, budgets, jobs, legal, llmops, strategies
from vp.platform.config import Settings
from vp.platform.db import tenant_session
from vp.platform.mail import Mailer, Message, OutboxMailer
from vp.platform.observe import HTTP_REQUESTS, HTTP_SECONDS, exposition, span
from vp.platform.principal import AuthMethod, Principal
from vp.platform.storage import ObjectStore, SharedRoot, open_store
from vp.platform.views import WorkspaceView
from vp.ui.server import STATIC

# Previews by spec hash and the data's modification times; a preview reads
# every resolved market of its domains, which is seconds for weather.
_PREVIEWS: dict[tuple[Any, ...], dict[str, Any]] = {}
_PREVIEW_LOCK = threading.Lock()

logger = logging.getLogger(__name__)

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
_API_REFERENCE = ("/docs", "/redoc")  # FastAPI's pages load their own scripts
_MARKET_ID = re.compile(r"^[0-9A-Za-z_-]{1,80}$")
_RUN_FILE = re.compile(r"^[a-z_]{1,64}\.(png|json|md|jsonl)$")
#: Sign-in requests per client address per hour, whatever the addresses.
SIGN_IN_PER_ADDRESS = 20
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
        "select to_regprocedure('vp_auth_sign_in(text, text)') is not null "
        "and to_regclass('public.user_settings') is not null"
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


class ConsentBody(BaseModel):
    """Accepting the terms and confirming one's age, from the app."""

    model_config = ConfigDict(extra="forbid")
    version: str
    adult: Literal[True]


class DeleteAccountBody(BaseModel):
    """Deleting one's account: the words typed must be exactly these."""

    model_config = ConfigDict(extra="forbid")
    confirm: Literal["delete my account"]


class TokenRequest(BaseModel):
    """A request to create an API token."""

    name: str = Field(min_length=1, max_length=100, pattern=r"\S")
    scope: Literal["read", "write"] = "read"


class Progress(BaseModel):
    """Where a person is in the guided start."""

    model_config = ConfigDict(extra="forbid")

    step: int = Field(default=0, ge=0, le=10)
    done: bool = False


class SettingsBody(BaseModel):
    """A person's interface settings, as the page stores them.

    Unknown keys are refused, so the stored document only ever holds what
    this model names; every field has a default, so an empty document is
    a valid one.
    """

    model_config = ConfigDict(extra="forbid")

    level: Literal["simple", "detailed"] = "simple"
    theme: Literal["system", "light", "dark"] = "system"
    locale: Literal["en-GB", "en-US"] | None = None  # None: the browser's
    interests: list[str] = Field(default_factory=list, max_length=50)
    follow: str | None = Field(default=None, pattern=r"^[a-z0-9_.-]{1,64}$")
    start: Progress = Field(default_factory=Progress)

    @field_validator("interests")
    @classmethod
    def known_domains(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(DOMAINS))
        if unknown:
            raise ValueError(f"unknown interests: {', '.join(unknown)}")
        return list(dict.fromkeys(value))


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


def writer(principal: Reader) -> Principal:
    """A reader whose role and credential may change the workspace's data."""
    if not principal.may_write:
        raise HTTPException(403, "your role or token may not start work here")
    return principal


Writer = Annotated[Principal, Depends(writer)]


class BacktestRequest(BaseModel):
    """A backtest to run: what the page's form and the API send."""

    model_config = ConfigDict(extra="forbid")

    domain: str
    forecasters: list[str] = Field(default_factory=lambda: ["market", "constant"])
    hours_before_close: float = Field(default=24.0, ge=1, le=720)
    kinds: list[str] = Field(default_factory=list, max_length=10)
    max_markets: int | None = Field(default=None, ge=1, le=5000)
    batch: bool = False
    model: str | None = None

    @field_validator("domain")
    @classmethod
    def known_domain(cls, value: str) -> str:
        if value not in DOMAINS:
            raise ValueError(f"unknown domain {value!r}")
        return value

    @field_validator("forecasters")
    @classmethod
    def known_forecasters(cls, value: list[str]) -> list[str]:
        from vp.forecast import FORECASTER_NAMES

        unknown = sorted(set(value) - set(FORECASTER_NAMES))
        if unknown or not value or len(value) > 5:
            raise ValueError(f"choose one to five of {', '.join(FORECASTER_NAMES)}")
        return list(dict.fromkeys(value))

    @field_validator("model")
    @classmethod
    def known_model(cls, value: str | None) -> str | None:
        from vp.forecast.llm import PRICES

        if value is not None and value not in PRICES:
            raise ValueError(f"unknown model {value!r}")
        return value


class CompileBody(BaseModel):
    """One message of a strategy conversation."""

    model_config = ConfigDict(extra="forbid")

    words: str = Field(min_length=1, max_length=2000)
    conversation_id: UUID | None = None
    strategy_id: UUID | None = None


class ConfirmBody(BaseModel):
    """Which proposed spec to freeze as a version: never the spec itself."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    turn_id: int


class StrategyBacktestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_markets: int | None = Field(default=None, ge=1, le=5000)


class MemoryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=300)


class PackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=60000)


class KeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=20, max_length=300)


def _eligible_kinds(path: Path) -> dict[str | None, int]:
    """Markets a backtest can select from a dataset, counted by kind (the
    rule of `vp.backtest.run.select_markets`)."""
    from vp.forecast.evidence import settled_at
    from vp.markets.store import read_markets

    counts: dict[str | None, int] = {}
    for m in read_markets(path):
        if m.resolved_outcome is not None and settled_at(m) is not None:
            kind = m.parsed.get("kind")
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def _json(value: Any) -> Response:
    """A view's answer, encoded directly.

    The views return plain JSON values, so FastAPI's `jsonable_encoder`,
    which walks every value in Python, is skipped: on a 2.4 MB market list
    it took 135 ms against 22 ms for `json.dumps` (docs/platform.md).
    """
    return Response(json.dumps(value, default=str), media_type="application/json")


def create_app(
    settings: Settings,
    *,
    mailer: Mailer | None = None,
    pool: ConnectionPool | None = None,
    store: ObjectStore | None = None,
    sign_in_limit: int = SIGN_IN_PER_ADDRESS,
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
    store = store or open_store(settings)
    shared = SharedRoot(store, settings.cache)
    stop = threading.Event()

    def refresh_shared() -> None:
        try:
            shared.refresh(DOMAINS)
        except Exception:  # noqa: BLE001 - the views read what the cache holds
            logger.exception("could not refresh the shared cache")

    def keep_fresh() -> None:
        """Refresh the shared cache when the ingest or a job says there is
        something new (NOTIFY vp_data), and once a minute regardless."""
        while not stop.is_set():
            try:
                with psycopg.connect(settings.database_url, autocommit=True) as conn:
                    conn.execute("listen vp_data")
                    while not stop.is_set():
                        notes = list(conn.notifies(timeout=60.0, stop_after=1))
                        refresh_shared()
                        del notes
            except Exception:  # noqa: BLE001 - retry; the minute timer covers it
                logger.exception("vp_data listener lost its connection")
                stop.wait(5.0)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        pool.open(wait=True, timeout=10)
        try:
            with pool.connection() as conn:
                check_database(conn)
            refresh_shared()
            threading.Thread(target=keep_fresh, daemon=True).start()
            yield
        finally:
            stop.set()
            pool.close()

    def view_for(principal: Principal) -> WorkspaceView:
        return WorkspaceView(shared, pool, principal, store)

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
        started = time.monotonic()
        with span("request", method=request.method, path=request.url.path):
            response = await call_next(request)
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        HTTP_REQUESTS.labels(template, request.method, str(response.status_code)).inc()
        HTTP_SECONDS.labels(template).observe(time.monotonic() - started)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if not request.url.path.startswith(_API_REFERENCE):
            response.headers.setdefault("Content-Security-Policy", _CSP)
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
    def request_link(
        request: Request, email: Annotated[str, Form()] = ""
    ) -> HTMLResponse:
        """Send a sign-in link. Answers the same whether or not one was sent."""
        address = auth.normalize_email(email)
        if address is None:
            return _page(
                "Sign in",
                _sign_in_form("That does not look like an email address."),
                status=422,
            )
        client = request.client.host if request.client else "unknown"
        with pool.connection() as conn:
            allowed = conn.execute(
                "select vp_rate_limit(%s, %s, %s)",
                (f"sign-in-ip:{client}", sign_in_limit, 3600),
            ).fetchone()
            if not allowed or not allowed[0]:
                return _page(
                    "Sign in",
                    _sign_in_form(
                        "Too many sign-in requests from your network this hour. "
                        "Try again later."
                    ),
                    status=429,
                )
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
        return _page("Sign in", _confirm_form(token))

    @app.post("/auth/verify", include_in_schema=False, response_model=None)
    def verify(
        token: Annotated[str, Form()] = "", agree: Annotated[str, Form()] = ""
    ) -> Response:
        # The age and the terms are confirmed before the token is spent, so
        # a person who has not ticked the box can still use the same link.
        if agree != "on":
            return _page(
                "Sign in",
                _confirm_form(token, "Please confirm your age and the terms first."),
                status=422,
            )
        with pool.connection() as conn:
            result = auth.sign_in(conn, token) if token else None
        if result is None:
            return _page(
                "Link expired",
                "<h1>That link has expired</h1><p>Sign-in links work once and "
                'for 15 minutes. <a href="/sign-in">Ask for a new one</a>.</p>',
                status=400,
            )
        with pool.connection() as conn:
            signed_in = auth.resolve_session(conn, result.session)
        if signed_in is not None:
            with pool.connection() as conn, tenant_session(conn, signed_in):
                conn.execute("select vp_accept_terms(%s)", (legal.TERMS_VERSION,))
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
            consent = conn.execute("select * from vp_consent()").fetchone()
        accepted = consent[0] if consent else None
        return {
            "consent": {
                "version": accepted,
                "required": legal.TERMS_VERSION,
                "current": accepted == legal.TERMS_VERSION
                and bool(consent and consent[2]),
            },
            "email": user[0] if user else None,
            "workspace": {"id": workspace[0], "name": workspace[1]}
            if workspace
            else None,
            "roles": sorted(principal.roles),
            "auth_method": principal.auth_method,
        }

    @app.post("/api/consent", status_code=204)
    def accept_terms(body: ConsentBody, principal: BrowserSession) -> None:
        """Accept the current terms and confirm one's age (18 or older)."""
        if body.version != legal.TERMS_VERSION:
            raise HTTPException(409, "the terms have changed; reload to read them")
        with pool.connection() as conn, tenant_session(conn, principal):
            conn.execute("select vp_accept_terms(%s)", (legal.TERMS_VERSION,))

    @app.delete("/api/account", response_model=None)
    def delete_account(
        body: DeleteAccountBody, principal: BrowserSession, request: Request
    ) -> Response:
        """Delete the signed-in person: their workspace and everything in it
        when they are its only member, their own rows, their stored files and
        archived rows, and their user. It cannot be undone."""
        from vp.platform.archive import purge_workspace

        with pool.connection() as conn, tenant_session(conn, principal):
            (deleted,) = conn.execute("select vp_delete_account()").fetchone() or (
                None,
            )
        files = 0
        if deleted is not None:
            for key in store.keys(f"workspaces/{deleted}/"):
                store.delete(key)
                files += 1
            files += purge_workspace(store, deleted)
        with pool.connection() as conn:
            audit.append(
                conn,
                "account.delete",
                {"workspace": principal.workspace, "workspace_deleted": bool(deleted)},
                principal,
            )
        response = JSONResponse({"deleted": True, "files_and_rows_purged": files})
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response

    @app.get("/terms", include_in_schema=False)
    def terms_page() -> HTMLResponse:
        return _page("Terms of use", legal.render("Terms of use", legal.TERMS))

    @app.get("/privacy", include_in_schema=False)
    def privacy_page() -> HTMLResponse:
        return _page("Privacy", legal.render("Privacy notice", legal.PRIVACY))

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

    # ------------------------------------------------------------ settings

    @app.get("/api/settings")
    def get_settings(principal: Reader) -> SettingsBody:
        """Your interface settings; the defaults until you save any."""
        with pool.connection() as conn, tenant_session(conn, principal):
            row = conn.execute("select settings from user_settings").fetchone()
        try:
            return SettingsBody.model_validate(row[0] if row else {})
        except ValidationError:
            # A document saved under an older shape (a domain since removed,
            # say) falls back to the defaults rather than failing the page.
            return SettingsBody()

    @app.put("/api/settings")
    def put_settings(body: SettingsBody, principal: BrowserSession) -> SettingsBody:
        """Replace your interface settings."""
        with pool.connection() as conn, tenant_session(conn, principal):
            conn.execute(
                "insert into user_settings (user_id, settings) "
                "values (vp_current_user_id(), %s) on conflict (user_id) do "
                "update set settings = excluded.settings, updated_at = now()",
                (Jsonb(body.model_dump()),),
            )
        return body

    # ----------------------------------------------------------- dashboard

    @app.get("/api/overview")
    def overview(principal: Reader) -> Response:
        """Per-domain counts, the paper accounts, and the workspace's account."""
        return _json(view_for(principal).overview())

    @app.get("/api/backtests")
    def backtests(principal: Reader) -> Response:
        """The workspace's backtest runs, newest first."""
        return _json(view_for(principal).backtests())

    @app.get("/api/runs/{run_id}/{name}")
    def run_file(run_id: UUID, name: str, principal: Reader) -> Response:
        """One file of one of the workspace's runs (results, summary, figures)."""
        if not _RUN_FILE.match(name):
            raise HTTPException(404, "no such file")
        with pool.connection() as conn, tenant_session(conn, principal):
            row = conn.execute(
                "select artifacts from runs where id = %s", (run_id,)
            ).fetchone()
        data = store.get_bytes(f"{row[0]}/{name}") if row and row[0] else None
        if data is None:
            raise HTTPException(404, "no such file")
        media = {"png": "image/png", "json": "application/json"}.get(
            name.rsplit(".", 1)[-1], "text/plain; charset=utf-8"
        )
        return Response(data, media_type=media)

    @app.get("/api/paper")
    def paper(
        principal: Reader, limit: Annotated[int, Query(ge=1, le=1000)] = 50
    ) -> Response:
        """The workspace's paper ledger: integrity, accounts, positions, settlements."""
        return _json(view_for(principal).paper(limit=limit))

    @app.get("/api/paper/export")
    def paper_export(principal: Reader) -> Response:
        """The paper ledger the workspace reads (its own account's, or the
        sample strategies'), as JSON lines, to verify offline."""
        view = view_for(principal)
        if view.account is None and view.sample is None:
            raise HTTPException(404, "there is no paper ledger yet")
        entries = view.ledger().entries()
        return Response(
            "".join(json.dumps(e, sort_keys=True) + "\n" for e in entries),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": 'attachment; filename="ledger.jsonl"'},
        )

    @app.get("/api/snapshots/{domain}")
    def snapshot(domain: str, principal: Reader) -> Response:
        """The latest capture of a domain's open markets."""
        if domain not in DOMAINS:
            raise HTTPException(404, "no such domain")
        return _json(view_for(principal).snapshot(domain))

    @app.get("/api/markets/{domain}/{market_id}")
    def market(domain: str, market_id: str, principal: Reader) -> Response:
        """One market: book depth, fee, forecasts and its recent prices."""
        found = (
            view_for(principal).market(domain, market_id)
            if domain in DOMAINS and _MARKET_ID.match(market_id)
            else None
        )
        if found is None:
            raise HTTPException(404, "no such market")
        return _json(found)

    @app.get("/api/forecasts")
    def forecasts(
        principal: Reader, limit: Annotated[int, Query(ge=1, le=1000)] = 100
    ) -> Response:
        """The workspace's most recent forecasts."""
        return _json(view_for(principal).forecasts(limit=limit))

    # ----------------------------------------------------------------- work

    @app.get("/api/capabilities")
    def capabilities(principal: Reader) -> dict[str, Any]:
        """What this service can do for this workspace."""
        own = llmops.key_hint(pool, principal)
        return {
            "llm": bool(settings.anthropic_api_key or own),
            "own_keys": bool(settings.master_key),
            "own_key_hint": own,
            "jobs": sorted(jobs.WORKSPACE_KINDS),
        }

    @app.get("/api/jobs")
    def list_jobs(
        principal: Reader, limit: Annotated[int, Query(ge=1, le=200)] = 30
    ) -> list[dict[str, Any]]:
        """The workspace's recent jobs, newest first, with their progress."""
        return jobs.workspace_jobs(pool, principal, limit=limit)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: UUID, principal: Reader) -> dict[str, Any]:
        found = [
            j
            for j in jobs.workspace_jobs(pool, principal, limit=200)
            if j["id"] == job_id
        ]
        if not found:
            raise HTTPException(404, "no such job")
        return found[0]

    @app.post("/api/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(job_id: UUID, principal: Writer) -> dict[str, Any]:
        if not jobs.request_cancel(pool, principal, job_id):
            raise HTTPException(404, "no such job, or it has already finished")
        return {"id": job_id, "cancel_requested": True}

    def _estimate(body: BacktestRequest) -> dict[str, Any]:
        from vp.forecast.llm import DEFAULT_MODEL, estimate_usd
        from vp.ui.server import cached_file

        path = shared.root / "markets" / body.domain / "resolved.parquet"
        if not path.exists():
            raise HTTPException(409, "this domain's data has not arrived yet")
        # How many markets the backtest selects depends only on each
        # eligible market's kind, so a count per kind is kept per dataset
        # version; parsing weather's 146,000 markets took 5.5 s a request.
        kinds = cached_file(path, _eligible_kinds) or {}
        markets = sum(n for k, n in kinds.items() if not body.kinds or k in body.kinds)
        if body.max_markets is not None:
            markets = min(markets, body.max_markets)
        usd = (
            estimate_usd(markets, body.model or DEFAULT_MODEL, batch=body.batch)
            if "llm" in body.forecasters
            else 0.0
        )
        return {"markets": markets, "estimate_usd": round(usd, 4)}

    @app.post("/api/backtests/estimate")
    def estimate_backtest(body: BacktestRequest, principal: Reader) -> dict[str, Any]:
        """What a backtest would cover and cost, before it runs."""
        standing = budgets.standing(pool, principal)
        return _estimate(body) | {
            "remaining_usd": float(standing.remaining_usd),
            "limit_usd": float(standing.limit_usd),
        }

    @app.post("/api/backtests", status_code=202)
    def start_backtest(body: BacktestRequest, principal: Writer) -> dict[str, Any]:
        """Queue a backtest; its progress is at /api/jobs/{id}."""
        estimate = _estimate(body)
        paid_by_platform = llmops.key_hint(pool, principal) is None
        if "llm" in body.forecasters:
            if not (settings.anthropic_api_key or not paid_by_platform):
                raise HTTPException(409, "no model key is available for this workspace")
        reserved = estimate["estimate_usd"] if paid_by_platform else 0.0
        try:
            budgets.reserve(pool, principal, reserved)
        except budgets.OverBudget as exc:
            raise HTTPException(402, str(exc)) from None
        payload = body.model_dump()
        try:
            job_id = jobs.enqueue(
                pool, principal, "backtest", payload, reserved_usd=reserved
            )
        except Exception:
            budgets.settle_job(pool, principal, UUID(int=0), reserved, [])
            raise
        return {"job_id": job_id, **estimate}

    @app.post("/api/paper/run", status_code=202)
    def run_paper(principal: Writer, what: str = "cycle") -> dict[str, Any]:
        """Run a paper cycle or a settlement pass of the workspace's own
        account now. The sample account everyone reads runs every hour on
        its own."""
        kind = {"cycle": "paper_cycle", "settle": "settle"}.get(what)
        if kind is None:
            raise HTTPException(422, "what must be cycle or settle")
        account = view_for(principal).account
        if account is None:
            raise HTTPException(
                409, "the sample strategies run every hour on their own"
            )
        return {
            "job_id": jobs.enqueue(
                pool, principal, kind, {"account_id": str(account["id"])}
            )
        }

    @app.post("/api/refresh/{domain}", status_code=202)
    def refresh_domain(domain: str, principal: Writer) -> dict[str, Any]:
        """Ask for a fresh capture of a domain's markets; at most one per
        domain every fifteen minutes, whoever asks."""
        from datetime import UTC, datetime

        if domain not in DOMAINS:
            raise HTTPException(404, "no such domain")
        now = datetime.now(tz=UTC)
        window = now.replace(
            minute=now.minute - now.minute % 15, second=0, microsecond=0
        )
        job_id = jobs.enqueue_platform(
            pool,
            "snapshot",
            {"domain": domain},
            idempotency_key=f"refresh:{domain}:{window:%Y%m%dT%H%M}",
            priority=jobs.PRIORITY_INTERACTIVE,
        )
        return {"queued": job_id is not None}

    @app.get("/api/spend")
    def spend(principal: Reader) -> dict[str, Any]:
        """This month's model spending: the budget, what is used, by what."""
        standing = budgets.standing(pool, principal)
        return {
            "limit_usd": float(standing.limit_usd),
            "charged_usd": float(standing.charged_usd),
            "reserved_usd": float(standing.reserved_usd),
            "remaining_usd": float(standing.remaining_usd),
            "breakdown": budgets.breakdown(pool, principal),
        }

    @app.get("/api/keys")
    def get_key(principal: BrowserSession) -> dict[str, Any]:
        return {
            "hint": llmops.key_hint(pool, principal),
            "enabled": bool(settings.master_key),
        }

    @app.put("/api/keys")
    def put_key(body: KeyBody, principal: BrowserSession) -> dict[str, Any]:
        """Store the workspace's own model key, encrypted; only a hint comes back."""
        if not principal.may_write:
            raise HTTPException(403, "your role may not change keys")
        try:
            hint = llmops.store_key(pool, principal, body.key, settings.master_key)
        except llmops.KeysUnavailable as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return {"hint": hint}

    @app.delete("/api/keys", status_code=204)
    def delete_key(principal: BrowserSession) -> Response:
        llmops.delete_key(pool, principal)
        return Response(status_code=204)

    # ------------------------------------------------------------ strategies

    def _found(fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except strategies.NotFound as exc:
            raise HTTPException(404, str(exc)) from None

    @app.post("/api/strategies/compile", status_code=202)
    def compile_strategy(body: CompileBody, principal: Writer) -> dict[str, Any]:
        """Send one message to the strategy compiler; the answer arrives as a
        turn of the conversation when the job is done."""
        paid_by_platform = llmops.key_hint(pool, principal) is None
        if paid_by_platform and not settings.anthropic_api_key:
            raise HTTPException(409, "no model key is available for this workspace")
        convo = body.conversation_id or _found(
            lambda: strategies.open_conversation(pool, principal, body.strategy_id)
        )
        _found(lambda: strategies.conversation(pool, principal, convo))
        reserved = strategies.COMPILE_RESERVE_USD if paid_by_platform else 0.0
        try:
            budgets.reserve(pool, principal, reserved)
        except budgets.OverBudget as exc:
            raise HTTPException(402, str(exc)) from None
        job_id = jobs.enqueue(
            pool,
            principal,
            "compile",
            {"conversation_id": str(convo), "words": body.words},
            reserved_usd=reserved,
        )
        return {"job_id": job_id, "conversation_id": convo}

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: UUID, principal: Reader) -> dict[str, Any]:
        return _found(lambda: strategies.conversation(pool, principal, conversation_id))

    @app.post("/api/strategies/confirm", status_code=201)
    def confirm_strategy(body: ConfirmBody, principal: Writer) -> dict[str, Any]:
        """Freeze a proposed spec as a new version, exactly as rendered."""
        try:
            return _found(
                lambda: strategies.confirm(
                    pool, principal, body.conversation_id, body.turn_id
                )
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/strategies")
    def list_strategies(principal: Reader) -> list[dict[str, Any]]:
        return strategies.listing(pool, principal)

    @app.get("/api/strategies/{strategy_id}")
    def get_strategy(strategy_id: UUID, principal: Reader) -> dict[str, Any]:
        return _found(lambda: strategies.detail(pool, principal, strategy_id))

    @app.get("/api/strategies/{strategy_id}/preview")
    def preview_strategy(strategy_id: UUID, principal: Reader) -> dict[str, Any]:
        """What the newest version would touch and cost, from data only."""
        head = _found(lambda: strategies.latest(pool, principal, strategy_id))
        out = _preview(head["spec"], head["spec_hash"])
        if principal.may_write:
            strategies.advance(pool, principal, strategy_id, "previewed")
        return out | {"version": head["version"], "spec_hash": head["spec_hash"]}

    def _preview(spec: Any, digest: str) -> dict[str, Any]:
        from vp.strategy.preview import preview

        stamp = tuple(
            (p.stat().st_mtime_ns if p.exists() else 0)
            for d in spec.selector.domains
            for p in (
                shared.root / "markets" / d / "resolved.parquet",
                shared.root / "snapshots" / d,
            )
        )
        key = (digest, stamp)
        with _PREVIEW_LOCK:
            hit = _PREVIEWS.get(key)
        if hit is None:
            hit = preview(spec, shared.root).as_json()
            with _PREVIEW_LOCK:
                _PREVIEWS[key] = hit
                while len(_PREVIEWS) > 128:
                    _PREVIEWS.pop(next(iter(_PREVIEWS)))
        return hit

    @app.post("/api/strategies/{strategy_id}/backtest", status_code=202)
    def backtest_strategy(
        strategy_id: UUID, body: StrategyBacktestBody, principal: Writer
    ) -> dict[str, Any]:
        """Backtest the newest version on each of its domains."""
        head = _found(lambda: strategies.latest(pool, principal, strategy_id))
        estimate = _preview(head["spec"], head["spec_hash"])["backtest_usd"]
        paid_by_platform = llmops.key_hint(pool, principal) is None
        if estimate and paid_by_platform and not settings.anthropic_api_key:
            raise HTTPException(409, "no model key is available for this workspace")
        reserved = estimate if paid_by_platform else 0.0
        try:
            budgets.reserve(pool, principal, reserved)
        except budgets.OverBudget as exc:
            raise HTTPException(402, str(exc)) from None
        job_id = jobs.enqueue(
            pool,
            principal,
            "backtest",
            {
                "strategy_version_id": str(head["version_id"]),
                "max_markets": body.max_markets,
            },
            reserved_usd=reserved,
        )
        return {"job_id": job_id, "estimate_usd": estimate, "version": head["version"]}

    @app.post("/api/strategies/{strategy_id}/paper", status_code=201)
    def paper_strategy(strategy_id: UUID, principal: Writer) -> dict[str, Any]:
        """Open the newest version's paper account; it trades on schedule."""
        try:
            return _found(lambda: strategies.start_paper(pool, principal, strategy_id))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/strategies/{strategy_id}/retire", status_code=204)
    def retire_strategy(strategy_id: UUID, principal: Writer) -> Response:
        _found(lambda: strategies.retire(pool, principal, strategy_id))
        return Response(status_code=204)

    @app.get("/api/strategies/{strategy_id}/paper")
    def strategy_paper(strategy_id: UUID, principal: Reader) -> dict[str, Any]:
        """The paper record of the strategy's newest account."""
        found = _found(lambda: strategies.detail(pool, principal, strategy_id))
        if not found["accounts"]:
            raise HTTPException(404, "this strategy has not traded in paper")
        account = found["accounts"][-1]
        view = WorkspaceView(
            shared, pool, principal, store, account_id=UUID(account["id"])
        )
        return {"account": account, "paper": view.paper()}

    @app.get("/api/memory")
    def get_memory(principal: Reader) -> list[dict[str, Any]]:
        """What the person asked the assistant to remember; theirs alone."""
        return strategies.memory(pool, principal)

    @app.post("/api/memory", status_code=201)
    def add_memory(body: MemoryBody, principal: Reader) -> dict[str, Any]:
        try:
            return {"id": strategies.remember(pool, principal, body.note)}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.delete("/api/memory/{note_id}", status_code=204)
    def delete_memory(note_id: UUID, principal: Reader) -> Response:
        if not strategies.forget(pool, principal, note_id):
            raise HTTPException(404, "no such note")
        return Response(status_code=204)

    @app.get("/api/packs/{domain}")
    def get_pack(domain: str, principal: Reader) -> dict[str, Any]:
        """The platform's pack for a domain and the workspace's copy, if any."""
        from vp.domains.pack import load

        platform_pack = load(domain)
        if platform_pack is None:
            raise HTTPException(404, "no pack for that domain")
        own = strategies.workspace_packs(pool, principal).get(domain)
        own_pack = load(domain, own) if own else None
        return {
            "platform": {
                "body": (PACKS / f"{domain}.md").read_text(),
                "sha256": platform_pack.sha256,
            },
            "workspace": {"body": own, "sha256": own_pack.sha256} if own_pack else None,
        }

    @app.put("/api/packs/{domain}")
    def put_pack(domain: str, body: PackBody, principal: Writer) -> dict[str, Any]:
        if domain not in DOMAINS:
            raise HTTPException(404, "no such domain")
        try:
            return {"sha256": strategies.save_pack(pool, principal, domain, body.body)}
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.delete("/api/packs/{domain}", status_code=204)
    def delete_pack(domain: str, principal: Writer) -> Response:
        strategies.drop_pack(pool, principal, domain)
        return Response(status_code=204)

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        """Prometheus metrics, for the operator's scraper only."""
        token = settings.metrics_token
        given = request.headers.get("authorization", "")
        if not token or not hmac.compare_digest(given, f"Bearer {token}"):
            raise HTTPException(404, "not found")
        return Response(
            exposition(settings.metrics_dir), media_type="text/plain; version=0.0.4"
        )

    # ---------------------------------------------------------------- page

    app.mount("/fonts", StaticFiles(directory=STATIC / "fonts"), name="fonts")
    app.mount("/app", StaticFiles(directory=STATIC / "app"), name="app")

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
        f"<p class=note>{html.escape(legal.STATEMENT)} "
        f"{html.escape(legal.JURISDICTION)}</p>" + _LEGAL_LINKS
    )


_LEGAL_LINKS = (
    '<p class=note><a href="/terms">Terms of use</a> · '
    '<a href="/privacy">Privacy</a></p>'
)


def _confirm_form(token: str, error: str = "") -> str:
    message = f"<p class=error role=alert>{html.escape(error)}</p>" if error else ""
    return (
        "<h1>Sign in to vibe-predict</h1>"
        f"<p>{html.escape(legal.STATEMENT)}</p>" + message + '<form method="post" '
        'action="/auth/verify">'
        f'<input type="hidden" name="token" value="{html.escape(token)}">'
        "<label class=check><input type=checkbox name=agree required> <span>"
        f"I am {legal.MINIMUM_AGE} or older, and I accept the "
        '<a href="/terms" target="_blank">terms of use</a> and the '
        '<a href="/privacy" target="_blank">privacy notice</a>.</span></label>'
        "<button type=submit>Sign in</button></form>"
    )


_STYLE = """
@font-face { font-family: "Instrument Sans";
  src: url(/fonts/InstrumentSans-latin.woff2) format("woff2");
  font-weight: 400 700; font-display: swap; }
/* The app's "paper" palette (docs/interface.md), measured at WCAG AA. */
:root { color-scheme: light dark; --plane: #FAF8F3; --surface: #FFFEFB;
  --ink: #1B1B1F; --ink-2: #5C5B57; --ring: #E4E0D6;
  --accent: #0F6E63; --on-accent: #FFFFFF; --bad: #B3261E; }
@media (prefers-color-scheme: dark) { :root { --plane: #121316;
  --surface: #17181C; --ink: #E8E6DF; --ink-2: #A3A198; --ring: #2A2B30;
  --accent: #4FB3A6; --on-accent: #121316; --bad: #F07A6E; } }
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
  border: 0; border-radius: 8px; background: var(--accent); color: var(--on-accent);
  cursor: pointer; }
button:focus-visible, input:focus-visible, a:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 2px; }
a { color: var(--accent); }
.error { color: var(--bad); }
label.check { display: flex; gap: 10px; align-items: flex-start; font-weight: 400;
  margin-bottom: 16px; }
label.check input { width: 20px; height: 20px; margin: 2px 0 0; flex: none; }
main:has(h2) { max-width: 680px; }
h2 { font-size: 17px; margin: 22px 0 6px; }
.note { font-size: 13px; }
code { font-size: 12px; word-break: break-all; }
"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width, initial-scale=1">'
        '<link rel=icon href="data:,">'
        f"<title>{html.escape(title)} · vibe-predict</title>"
        f"<style>{_STYLE}</style></head><body><main>"
        f"<div class=brand>vibe-predict</div>{body}</main></body></html>",
        status_code=status,
    )
