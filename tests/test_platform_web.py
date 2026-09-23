"""The web service end to end, against a real database.

Skips unless both database URLs are set (see `tests/test_platform_db.py`).
Every sign-in goes the way a person's would: ask for a link, read it from
the mail outbox, open it, press the button.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from vp.platform.auth import SESSION_COOKIE, digest
from vp.platform.config import Settings
from vp.platform.db import connect, migrate
from vp.platform.mail import OutboxMailer
from vp.platform.web import DatabaseRoleError, create_app

OWNER_URL = os.environ.get("VP_TEST_DATABASE_URL", "")
APP_URL = os.environ.get("VP_TEST_APP_DATABASE_URL", "")
ORIGIN = {"Origin": "http://testserver"}

pytestmark = pytest.mark.skipif(
    not (OWNER_URL and APP_URL),
    reason="set VP_TEST_DATABASE_URL and VP_TEST_APP_DATABASE_URL",
)


@pytest.fixture(scope="module")
def owner() -> Iterator:
    conn = connect(OWNER_URL)
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def mailer() -> OutboxMailer:
    return OutboxMailer()


@pytest.fixture(scope="module")
def client(
    owner, mailer: OutboxMailer, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[TestClient]:
    settings = Settings(
        database_url=APP_URL,
        data_root=tmp_path_factory.mktemp("data"),
        public_url="http://testserver",
    )
    with TestClient(create_app(settings, mailer=mailer)) as test_client:
        yield test_client


def _email() -> str:
    return f"ada-{uuid4().hex[:10]}@example.test"


def _link_token(mailer: OutboxMailer, email: str) -> str:
    message = [m for m in mailer.sent if m.to == email][-1]
    line = next(ln for ln in message.body.splitlines() if "/auth/verify?token=" in ln)
    return line.split("token=", 1)[1].strip()


def _sign_in(client: TestClient, mailer: OutboxMailer, email: str) -> str:
    """Sign in as a person would, and return the session cookie."""
    client.cookies.clear()
    assert (
        client.post("/auth/sign-in", data={"email": email}, headers=ORIGIN).status_code
        == 200
    )
    token = _link_token(mailer, email)
    assert client.get(f"/auth/verify?token={token}").status_code == 200
    done = client.post(
        "/auth/verify", data={"token": token}, headers=ORIGIN, follow_redirects=False
    )
    assert done.status_code == 303 and done.headers["location"] == "/"
    cookie = done.cookies.get(SESSION_COOKIE)
    assert cookie
    return cookie


def _as(client: TestClient, cookie: str | None) -> TestClient:
    client.cookies.clear()
    if cookie:
        client.cookies.set(SESSION_COOKIE, cookie)
    return client


# ---------------------------------------------------------------- start-up


def test_the_service_refuses_to_start_as_a_role_rls_does_not_bind(
    owner, tmp_path: Path
) -> None:
    """The tenancy tests prove isolation for vp_app, so nothing else may serve."""
    app = create_app(Settings(database_url=OWNER_URL, data_root=tmp_path))
    with pytest.raises(DatabaseRoleError):
        with TestClient(app):
            pass


def test_health_and_readiness(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ready"}


# ----------------------------------------------------------------- sign-in


def test_without_a_session_everything_asks_you_to_sign_in(client: TestClient) -> None:
    _as(client, None)
    page = client.get("/", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/sign-in"
    assert client.get("/api/overview").status_code == 401
    assert client.get("/auth/me").status_code == 401
    assert "Send me a link" in client.get("/sign-in").text


def test_signing_in_by_email_link_creates_a_personal_workspace(
    client: TestClient, mailer: OutboxMailer
) -> None:
    email = _email()
    cookie = _sign_in(client, mailer, email)
    me = _as(client, cookie).get("/auth/me").json()
    assert me["email"] == email
    assert me["workspace"]["name"] == "Personal"
    assert me["roles"] == ["owner"]
    assert client.get("/", follow_redirects=False).status_code == 200
    assert client.get("/api/overview").status_code == 200


def test_opening_the_link_does_not_spend_it(
    client: TestClient, mailer: OutboxMailer
) -> None:
    """Mail scanners fetch every link; only the button signs in."""
    email = _email()
    _as(client, None).post("/auth/sign-in", data={"email": email}, headers=ORIGIN)
    token = _link_token(mailer, email)
    for _ in range(3):
        assert client.get(f"/auth/verify?token={token}").status_code == 200
    done = client.post(
        "/auth/verify", data={"token": token}, headers=ORIGIN, follow_redirects=False
    )
    assert done.status_code == 303


def test_a_link_works_once(client: TestClient, mailer: OutboxMailer) -> None:
    email = _email()
    _sign_in(client, mailer, email)
    token = _link_token(mailer, email)
    again = _as(client, None).post(
        "/auth/verify", data={"token": token}, headers=ORIGIN
    )
    assert again.status_code == 400
    assert "expired" in again.text


def test_an_expired_link_is_refused(
    client: TestClient, mailer: OutboxMailer, owner
) -> None:
    email = _email()
    _as(client, None).post("/auth/sign-in", data={"email": email}, headers=ORIGIN)
    token = _link_token(mailer, email)
    with owner.transaction():
        owner.execute(
            "update sign_in_tokens set expires_at = now() - interval '1 second' "
            "where token_hash = %s",
            (digest(token),),
        )
    refused = client.post("/auth/verify", data={"token": token}, headers=ORIGIN)
    assert refused.status_code == 400


def test_only_the_hash_of_a_link_is_stored(
    client: TestClient, mailer: OutboxMailer, owner
) -> None:
    email = _email()
    _as(client, None).post("/auth/sign-in", data={"email": email}, headers=ORIGIN)
    token = _link_token(mailer, email)
    rows = owner.execute(
        "select token_hash from sign_in_tokens where email = %s", (email,)
    ).fetchall()
    assert [r[0] for r in rows] == [digest(token)]


def test_the_answer_is_the_same_whether_or_not_a_link_was_sent(
    client: TestClient, mailer: OutboxMailer
) -> None:
    """Nothing in the response says whether an address exists or is limited."""
    email = _email()
    _as(client, None)
    bodies = {
        client.post("/auth/sign-in", data={"email": email}, headers=ORIGIN).text
        for _ in range(7)
    }
    assert len(bodies) == 1
    # Five per address per fifteen minutes; the other two were refused quietly.
    assert len([m for m in mailer.sent if m.to == email]) == 5


def test_an_impossible_address_is_told_so(client: TestClient) -> None:
    response = _as(client, None).post(
        "/auth/sign-in", data={"email": "not an address"}, headers=ORIGIN
    )
    assert response.status_code == 422


# --------------------------------------------------------- cross-site checks


def test_a_state_change_from_another_site_is_refused(
    client: TestClient, mailer: OutboxMailer
) -> None:
    email = _email()
    _as(client, None)
    assert client.post("/auth/sign-in", data={"email": email}).status_code == 403
    assert (
        client.post(
            "/auth/sign-in",
            data={"email": email},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert not [m for m in mailer.sent if m.to == email]


def test_another_site_cannot_sign_you_into_its_account(
    client: TestClient, mailer: OutboxMailer
) -> None:
    """Login cross-site request forgery: posting the attacker's own token."""
    email = _email()
    _as(client, None).post("/auth/sign-in", data={"email": email}, headers=ORIGIN)
    token = _link_token(mailer, email)
    forged = client.post(
        "/auth/verify",
        data={"token": token},
        headers={"Origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert forged.status_code == 403
    # Refused before it was spent: the owner of the link can still use it.
    ok = client.post(
        "/auth/verify", data={"token": token}, headers=ORIGIN, follow_redirects=False
    )
    assert ok.status_code == 303


# --------------------------------------------------------------- sessions


def test_signing_out_ends_the_session_on_the_server(
    client: TestClient, mailer: OutboxMailer
) -> None:
    cookie = _sign_in(client, mailer, _email())
    out = _as(client, cookie).post(
        "/auth/sign-out", headers=ORIGIN, follow_redirects=False
    )
    assert out.status_code == 303 and out.headers["location"] == "/sign-in"
    # Replaying the old cookie must not work: it is revoked, not just forgotten.
    assert _as(client, cookie).get("/auth/me").status_code == 401


def test_removing_a_membership_ends_its_sessions(
    client: TestClient, mailer: OutboxMailer, owner
) -> None:
    cookie = _sign_in(client, mailer, _email())
    workspace = _as(client, cookie).get("/auth/me").json()["workspace"]["id"]
    with owner.transaction():
        owner.execute("delete from memberships where workspace_id = %s", (workspace,))
    assert _as(client, cookie).get("/auth/me").status_code == 401


def test_two_people_each_see_only_their_own(
    client: TestClient, mailer: OutboxMailer
) -> None:
    ada, bob = _email(), _email()
    ada_cookie, bob_cookie = (
        _sign_in(client, mailer, ada),
        _sign_in(client, mailer, bob),
    )
    ada_me = _as(client, ada_cookie).get("/auth/me").json()
    client.post("/api/tokens", json={"name": "ada's"}, headers=ORIGIN)
    bob_me = _as(client, bob_cookie).get("/auth/me").json()
    assert ada_me["email"] == ada and bob_me["email"] == bob
    assert ada_me["workspace"]["id"] != bob_me["workspace"]["id"]
    assert client.get("/api/tokens").json() == []


# -------------------------------------------------------------- API tokens


def test_an_api_token_is_shown_once_and_acts_with_its_scope(
    client: TestClient, mailer: OutboxMailer
) -> None:
    cookie = _sign_in(client, mailer, _email())
    created = _as(client, cookie).post(
        "/api/tokens", json={"name": "laptop", "scope": "read"}, headers=ORIGIN
    )
    assert created.status_code == 201
    body = created.json()
    secret, token_id = body["token"], body["id"]

    listed = client.get("/api/tokens").json()
    assert [t["id"] for t in listed] == [token_id]
    assert "token" not in listed[0]

    bearer = {"Authorization": f"Bearer {secret}"}
    _as(client, None)
    assert client.get("/api/overview", headers=bearer).status_code == 200
    assert client.get("/auth/me", headers=bearer).json()["roles"] == ["viewer"]
    # A token cannot mint tokens, whatever its scope.
    assert (
        client.post("/api/tokens", json={"name": "x"}, headers=bearer).status_code
        == 403
    )

    revoked = _as(client, cookie).delete(f"/api/tokens/{token_id}", headers=ORIGIN)
    assert revoked.status_code == 204
    assert _as(client, None).get("/api/overview", headers=bearer).status_code == 401


def test_a_made_up_bearer_token_is_refused(client: TestClient) -> None:
    response = _as(client, None).get(
        "/api/overview", headers={"Authorization": "Bearer not-a-token"}
    )
    assert response.status_code == 401


# ------------------------------------------------------------------- views


def test_figure_paths_cannot_leave_the_data_root(
    client: TestClient, mailer: OutboxMailer
) -> None:
    _as(client, _sign_in(client, mailer, _email()))
    for path in (
        "/api/backtests/epl/..%2F..%2Fsecrets/x.png",
        "/api/backtests/epl/stamp/..png",
        "/api/backtests/nowhere/stamp/reliability.png",
        "/api/snapshots/nowhere",
        "/api/markets/nowhere/1",
        "/api/markets/epl/..%2Fx",
        "/api/markets/epl/12345",
    ):
        assert client.get(path).status_code == 404, path


def test_every_response_carries_the_security_headers(client: TestClient) -> None:
    response = _as(client, None).get("/sign-in")
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    verify = client.get("/auth/verify?token=x")
    assert verify.headers["Cache-Control"] == "no-store"
    # Scripts from this origin only, and no inline script, on every page but
    # FastAPI's API reference, which loads its own.
    csp = response.headers["Content-Security-Policy"]
    assert "script-src 'self';" in csp and "unsafe-inline" not in csp.split(";")[1]
    assert "Content-Security-Policy" not in client.get("/docs").headers


def test_the_server_path_is_not_shown(client: TestClient, mailer: OutboxMailer) -> None:
    _as(client, _sign_in(client, mailer, _email()))
    overview = client.get("/api/overview").json()
    assert "root" not in overview and "epl" in overview["domains"]
    assert overview["domains"]["epl"]["title"] == "Premier League"


# ---------------------------------------------------------------- settings


def test_settings_start_at_the_defaults_and_are_your_own(
    client: TestClient, mailer: OutboxMailer
) -> None:
    ada, bob = _sign_in(client, mailer, _email()), _sign_in(client, mailer, _email())
    defaults = _as(client, ada).get("/api/settings").json()
    assert defaults["level"] == "simple" and defaults["interests"] == []
    assert defaults["start"] == {"step": 0, "done": False}

    chosen = defaults | {
        "level": "detailed",
        "interests": ["weather", "epl", "weather"],
        "follow": "elo",
        "start": {"step": 3, "done": True},
    }
    saved = client.put("/api/settings", json=chosen, headers=ORIGIN)
    assert saved.status_code == 200 and saved.json()["interests"] == ["weather", "epl"]
    assert client.get("/api/settings").json()["level"] == "detailed"
    # Saving twice replaces the document rather than adding a row.
    client.put("/api/settings", json=chosen | {"theme": "dark"}, headers=ORIGIN)
    assert client.get("/api/settings").json()["theme"] == "dark"
    # Bob sees his own defaults, not Ada's choices.
    assert _as(client, bob).get("/api/settings").json()["level"] == "simple"


def test_settings_refuse_what_they_do_not_name(
    client: TestClient, mailer: OutboxMailer
) -> None:
    _as(client, _sign_in(client, mailer, _email()))
    for body in (
        {"level": "expert"},
        {"interests": ["nba"]},
        {"surprise": True},
        {"follow": "<script>"},
        {"start": {"step": 99}},
    ):
        assert client.put("/api/settings", json=body, headers=ORIGIN).status_code == (
            422
        ), body


def test_an_api_token_reads_settings_but_cannot_change_them(
    client: TestClient, mailer: OutboxMailer
) -> None:
    cookie = _sign_in(client, mailer, _email())
    secret = (
        _as(client, cookie)
        .post("/api/tokens", json={"name": "t", "scope": "write"}, headers=ORIGIN)
        .json()["token"]
    )
    bearer = {"Authorization": f"Bearer {secret}"}
    _as(client, None)
    assert client.get("/api/settings", headers=bearer).status_code == 200
    assert client.put("/api/settings", json={}, headers=bearer).status_code == 403


def test_nothing_personal_is_left_in_the_browser_cache(
    client: TestClient, mailer: OutboxMailer
) -> None:
    """A cached dashboard outlived sign-out in a real browser; no longer."""
    _as(client, _sign_in(client, mailer, _email()))
    for path in ("/", "/api/overview", "/auth/me"):
        assert client.get(path).headers["Cache-Control"] == "no-store", path
    assert "no-store" not in client.get(
        "/fonts/InstrumentSans-latin.woff2"
    ).headers.get("Cache-Control", "")
