"""Teams, sharing, comments, notifications and leaderboards, end to end
against the database (plan, tasks 81 to 84, 87; docs/collaboration.md).

Everyone signs in the way a person would, through the mail outbox."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from tests.test_platform_web import (  # noqa: F401 - fixtures
    ORIGIN,
    _as,
    _email,
    _sign_in,
    client,
    mailer,
    owner,
    pytestmark,
)
from vp.platform import leaderboards
from vp.platform.mail import OutboxMailer
from vp.platform.notify import quiet_until, routes


def _invite_token(outbox: OutboxMailer, email: str) -> str:
    message = [m for m in outbox.sent if m.to == email][-1]
    line = next(ln for ln in message.body.splitlines() if "/invite?token=" in ln)
    return line.split("token=", 1)[1].strip()


def _strategy(http: TestClient, db, email: str) -> str:
    """A confirmed strategy in the signed-in person's workspace."""
    from tests.test_strategy_compiler import GOOD

    workspace = http.get("/auth/me").json()["workspace"]["id"]
    (user,) = db.execute("select id from users where email = %s", (email,)).fetchone()
    with db.transaction():
        (convo,) = db.execute(
            "insert into conversations (workspace_id, user_id) values (%s, %s) "
            "returning id",
            (workspace, user),
        ).fetchone()
        (turn,) = db.execute(
            "insert into conversation_turns (conversation_id, workspace_id, role, "
            "content) values (%s, %s, 'assistant', %s) returning id",
            (convo, workspace, Jsonb({"kind": "spec", "spec": GOOD})),
        ).fetchone()
    made = http.post(
        "/api/strategies/confirm",
        json={"conversation_id": str(convo), "turn_id": turn},
        headers=ORIGIN,
    )
    assert made.status_code == 201, made.text
    return made.json()["strategy_id"]


def test_a_team_is_invited_joined_changed_and_left(
    client: TestClient,  # noqa: F811
    mailer: OutboxMailer,  # noqa: F811
    owner,  # noqa: F811
) -> None:
    ada, bob, eve = _email(), _email(), _email()
    ada_cookie = _sign_in(client, mailer, ada)
    bob_cookie = _sign_in(client, mailer, bob)
    eve_cookie = _sign_in(client, mailer, eve)
    _as(client, ada_cookie)
    home = client.get("/auth/me").json()["workspace"]["id"]
    sent = client.post(
        "/api/team/invitations", json={"email": bob, "role": "editor"}, headers=ORIGIN
    )
    assert sent.status_code == 201
    token = _invite_token(mailer, bob)
    # Only the invited address can use it.
    _as(client, eve_cookie)
    refused = client.post("/invite", data={"token": token}, headers=ORIGIN)
    assert refused.status_code == 400
    _as(client, bob_cookie)
    assert "Join" in client.get(f"/invite?token={token}").text
    joined = client.post(
        "/invite", data={"token": token}, headers=ORIGIN, follow_redirects=False
    )
    assert joined.status_code == 303 and joined.headers["location"] == "/#team"
    assert client.get("/auth/me").json()["workspace"]["id"] == home
    team = client.get("/api/team").json()
    assert sorted(m["role"] for m in team["members"]) == ["editor", "owner"]
    assert len(team["workspaces"]) == 2 and not team["you_may_administer"]
    # An editor may not invite or change roles.
    assert (
        client.post(
            "/api/team/invitations",
            json={"email": eve, "role": "viewer"},
            headers=ORIGIN,
        ).status_code
        == 403
    )
    # Teammates see each other's addresses, and only that.
    assert {m["email"] for m in team["members"]} == {ada, bob}
    # The owner makes bob a viewer; a viewer cannot start work.
    _as(client, ada_cookie)
    bob_id = next(m["user_id"] for m in team["members"] if m["email"] == bob)
    ada_id = next(m["user_id"] for m in team["members"] if m["email"] == ada)
    assert (
        client.put(
            f"/api/team/members/{bob_id}", json={"role": "viewer"}, headers=ORIGIN
        ).status_code
        == 204
    )
    # The last owner cannot leave a team while others are in it.
    left = client.delete(f"/api/team/members/{ada_id}", headers=ORIGIN)
    assert left.status_code == 409 and "owner" in left.json()["detail"]
    _as(client, bob_cookie)
    assert client.post("/api/paper/run", json={}, headers=ORIGIN).status_code == 403
    # Bob goes back to his own workspace, then leaves the team.
    mine = next(
        w for w in client.get("/api/team").json()["workspaces"] if w["id"] != home
    )
    assert (
        client.post(
            "/api/team/switch", json={"workspace_id": mine["id"]}, headers=ORIGIN
        ).status_code
        == 204
    )
    assert client.get("/auth/me").json()["workspace"]["id"] == mine["id"]
    assert (
        client.post(
            "/api/team/switch", json={"workspace_id": str(uuid4())}, headers=ORIGIN
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/team/switch", json={"workspace_id": home}, headers=ORIGIN
        ).status_code
        == 204
    )
    assert (
        client.delete(f"/api/team/members/{bob_id}", headers=ORIGIN).status_code == 204
    )
    # Leaving ends the session's access to the team.
    assert client.get("/api/team").status_code in (401, 403)
    _as(client, ada_cookie)
    feed = [a["action"] for a in client.get("/api/team/activity").json()]
    assert feed[:4] == ["left", "role_changed", "joined", "invited"]


def test_a_strategy_is_shared_viewed_forked_and_unshared(
    client: TestClient,  # noqa: F811
    mailer: OutboxMailer,  # noqa: F811
    owner,  # noqa: F811
) -> None:
    ada, bob = _email(), _email()
    ada_cookie, bob_cookie = (
        _sign_in(client, mailer, ada),
        _sign_in(client, mailer, bob),
    )
    _as(client, ada_cookie)
    sid = _strategy(client, owner, ada)
    made = client.put(
        f"/api/strategies/{sid}/share", json={"show_spec": True}, headers=ORIGIN
    )
    assert made.status_code == 200
    slug = made.json()["slug"]
    # Entering the leaderboards shows on the strategy's share answer.
    assert client.get(f"/api/strategies/{sid}/share").json()["leaderboard"] is None
    entered = client.put(
        f"/api/strategies/{sid}/leaderboard",
        json={"display_name": "Ada's picks"},
        headers=ORIGIN,
    )
    assert entered.status_code == 204
    got = client.get(f"/api/strategies/{sid}/share").json()
    assert got["leaderboard"] == "Ada's picks" and got["public_url"]
    # Anyone may look; nobody needs to sign in; P&L and author stay private.
    client.cookies.clear()
    public = client.get(f"/api/public/shares/{slug}").json()
    assert public["rendering"][0].startswith("Markets: Premier League")
    assert "paper" not in public and public["author"] is None and public["forkable"]
    page = client.get(f"/s/{slug}")
    assert page.status_code == 200 and "Copy this strategy" in page.text
    svg = client.get(f"/s/{slug}/card.svg")
    assert (
        svg.headers["content-type"].startswith("image/svg+xml") and "<svg" in svg.text
    )
    # Bob forks it into his own workspace; where it came from is kept.
    _as(client, bob_cookie)
    fork = client.post(f"/api/public/shares/{slug}/fork", headers=ORIGIN)
    assert fork.status_code == 201
    assert fork.json()["provenance"]["forked_from"] == slug
    assert [s["id"] for s in client.get("/api/strategies").json()] == [
        fork.json()["strategy_id"]
    ]
    _as(client, ada_cookie)
    share = client.get(f"/api/strategies/{sid}/share").json()["share"]
    assert share["forks"] == 1 and share["views"] >= 2
    # Without the spec, there is nothing to fork.
    client.put(f"/api/strategies/{sid}/share", json={}, headers=ORIGIN)
    _as(client, bob_cookie)
    assert (
        client.post(f"/api/public/shares/{slug}/fork", headers=ORIGIN).status_code
        == 403
    )
    _as(client, ada_cookie)
    assert (
        client.delete(f"/api/strategies/{sid}/share", headers=ORIGIN).status_code == 204
    )
    client.cookies.clear()
    assert client.get(f"/api/public/shares/{slug}").status_code == 404
    assert client.get(f"/s/{slug}").status_code == 404


def test_comments_mention_reply_and_are_moderated(
    client: TestClient,  # noqa: F811
    mailer: OutboxMailer,  # noqa: F811
    owner,  # noqa: F811
) -> None:
    ada, bob = _email(), _email()
    ada_cookie, bob_cookie = (
        _sign_in(client, mailer, ada),
        _sign_in(client, mailer, bob),
    )
    _as(client, ada_cookie)
    client.post(
        "/api/team/invitations", json={"email": bob, "role": "viewer"}, headers=ORIGIN
    )
    _as(client, bob_cookie)
    client.post("/invite", data={"token": _invite_token(mailer, bob)}, headers=ORIGIN)
    _as(client, ada_cookie)
    sid = _strategy(client, owner, ada)
    handle = bob.split("@")[0]
    first = client.post(
        "/api/comments",
        json={
            "subject_kind": "strategy",
            "subject_id": sid,
            "body": f"@{handle} does the draw price look stale?",
        },
        headers=ORIGIN,
    )
    assert first.status_code == 201
    # Bob (a viewer) is notified, by email too by default, and replies.
    _as(client, bob_cookie)
    notices = client.get("/api/notifications").json()
    assert notices["unread"] == 1 and notices["items"][0]["kind"] == "mention"
    assert any(m.to == bob and "mentioned you" in m.subject for m in mailer.sent) or (
        owner.execute(
            "select count(*) from outbox where address = %s", (bob,)
        ).fetchone()[0]
        == 1
    )
    reply = client.post(
        "/api/comments",
        json={
            "subject_kind": "strategy",
            "subject_id": sid,
            "body": "It was fetched an hour ago.",
            "parent": first.json()["id"],
        },
        headers=ORIGIN,
    )
    assert reply.status_code == 201
    assert client.post("/api/notifications/read", json={}, headers=ORIGIN).json() == {
        "marked": 1
    }
    # Bob cannot hide Ada's comment; he can correct his own for five minutes.
    assert (
        client.post(
            f"/api/comments/{first.json()['id']}/hide", headers=ORIGIN
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/comments/{reply.json()['id']}",
            json={"body": "Fetched fifty minutes ago."},
            headers=ORIGIN,
        ).status_code
        == 204
    )
    _as(client, ada_cookie)
    assert client.get("/api/notifications").json()["items"][0]["kind"] == "reply"
    assert (
        client.post(
            f"/api/comments/{reply.json()['id']}/hide", headers=ORIGIN
        ).status_code
        == 204
    )
    (thread,) = client.get(f"/api/comments/strategy/{sid}").json()
    assert (
        thread["body"].startswith("@") and thread["replies"][0]["removed"] == "hidden"
    )
    assert thread["replies"][0]["body"] is None


def test_notification_preferences_and_quiet_hours(
    client: TestClient,  # noqa: F811
    mailer: OutboxMailer,  # noqa: F811
) -> None:
    assert routes({}, "mention") == ["email"] and routes({}, "fill") == []
    assert routes({"kinds": {"fill": ["email", "sms"]}}, "fill") == ["email"]
    quiet = {"quiet": {"start": "22:00", "end": "07:00", "tz": "Europe/London"}}
    late = datetime(2026, 9, 23, 22, 30, tzinfo=UTC)  # 23:30 in London
    assert quiet_until(quiet, late) == datetime(2026, 9, 24, 6, 0, tzinfo=UTC)
    assert quiet_until(quiet, datetime(2026, 9, 23, 12, 0, tzinfo=UTC)) is None
    _as(client, _sign_in(client, mailer, _email()))
    got = client.put(
        "/api/notifications/prefs",
        json={"kinds": {"fill": ["email"]}, "quiet": quiet["quiet"]},
        headers=ORIGIN,
    )
    assert got.status_code == 200 and got.json()["kinds"]["fill"] == ["email"]
    bad = client.put(
        "/api/notifications/prefs", json={"kinds": {"gossip": []}}, headers=ORIGIN
    )
    assert bad.status_code == 409
    zone = {"start": "22:00", "end": "07:00", "tz": "Mars/Olympus"}
    bad = client.put("/api/notifications/prefs", json={"quiet": zone}, headers=ORIGIN)
    assert bad.status_code == 409 and "time zone" in bad.json()["detail"]
    # Secrets need the master key; without one the answer says so.
    hook = {"url": "https://example.test/h", "events": ["run.finished"]}
    refused = client.post("/api/webhooks", json=hook, headers=ORIGIN)
    assert refused.status_code == 503 and "master key" in refused.json()["detail"]


def test_a_market_comment_links_to_its_page() -> None:
    from vp.platform.comments import _link

    assert _link("market", "cs2:1234") == "#market/cs2/1234"
    assert _link("strategy", "abc") == "#strategy/abc"


def test_leaderboards_rank_only_with_enough_settled_positions() -> None:
    now = datetime(2026, 9, 24, tzinfo=UTC)
    rows = []
    for i in range(60):  # a strategy a little better than the market
        rows.append(("s1", "Steady", "epl", now - timedelta(days=i), 0.20, 0.22, 1.0))
    for i in range(10):  # a lucky newcomer
        rows.append(("s2", "Lucky", "cs2", now - timedelta(days=i), 0.05, 0.25, 9.0))
    boards = leaderboards.compute(rows, now)
    top = boards["all:all"]["entries"]
    assert top[0]["name"] == "Steady" and top[0]["rank"] == 1
    assert top[1]["name"] == "Lucky" and "rank" not in top[1] and not top[1]["ranked"]
    assert boards["epl:30d"]["entries"][0]["settled"] == 31  # days 0 to 30
    assert "cs2:all" in boards and boards["all:30d"]["min_ranked"] == 50
    assert top[0]["pnl"] == 60.0  # shown beside the skill, never the rank


def test_the_leaderboard_job_reads_only_opted_in_settlements(
    client: TestClient,  # noqa: F811
    mailer: OutboxMailer,  # noqa: F811
    owner,  # noqa: F811
    app_pool,
) -> None:
    from types import SimpleNamespace

    ada = _email()
    _as(client, _sign_in(client, mailer, ada))
    sid = _strategy(client, owner, ada)
    workspace = client.get("/auth/me").json()["workspace"]["id"]
    with owner.transaction():
        (vid,) = owner.execute(
            "select id from strategy_versions where strategy_id = %s", (sid,)
        ).fetchone()
        (acct,) = owner.execute(
            "insert into paper_accounts (workspace_id, name, domains, forecasters, "
            "strategy_version_id) values (%s, %s, '{epl}', '{elo}', %s) returning id",
            (workspace, f"lb-{sid[:8]}", vid),
        ).fetchone()
        at = datetime.now(tz=UTC)
        for seq, (kind, data) in enumerate(
            [
                ("order", {"market_id": "m1", "domain": "epl"}),
                (
                    "settlement",
                    {"market_id": "m1", "brier": 0.1, "brier_market": 0.2, "pnl": 3.0},
                ),
            ]
        ):
            owner.execute(
                "insert into ledger_entries (account_id, workspace_id, seq, at, kind, "
                "entry, hash) values (%s, %s, %s, %s, %s, %s, 'h')",
                (acct, workspace, seq, at, kind, Jsonb({"data": data})),
            )
    ctx = SimpleNamespace(pool=app_pool)
    leaderboards.run(ctx)
    assert not any(
        e["strategy_id"] == sid
        for body in leaderboards.read(app_pool).values()
        for e in body["entries"]
    )
    assert (
        client.put(
            f"/api/strategies/{sid}/leaderboard",
            json={"display_name": "Ada's Elo"},
            headers=ORIGIN,
        ).status_code
        == 204
    )
    leaderboards.run(ctx)
    board = client.get("/api/leaderboards").json()["epl:all"]
    mine = next(e for e in board["entries"] if e["strategy_id"] == sid)
    assert mine["name"] == "Ada's Elo" and mine["settled"] == 1 and not mine["ranked"]
    with owner.transaction():
        owner.execute("delete from paper_accounts where id = %s", (acct,))
