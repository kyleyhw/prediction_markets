# Phase 18 Test Report: Collaboration and Delivery

Date: 2026-09-24. Environment: Python 3.14.7 via `uv 0.12.18`, Postgres 16
in the development container, `vp serve` and `vp worker` on the local
stand-in for cloud hosting (flag F16), Chromium 1.x with axe-core. No chat
platform, mail server or webhook receiver outside the machine was
contacted: email goes to the stand-in's outbox directory, and the chat and
webhook adapters were driven through a recording stand-in for the network
that answers, or fails, as each platform documents.

## Purpose

Collaboration adds teams, public shares, comments and leaderboards to the
platform. Delivery gets research to people where they already are: email,
chats, webhooks and a read-only tool server. Until now each workspace had
one person working in the browser. The design went into
`docs/collaboration.md` first, and its decisions were taken as proposed.

## Static Checks and Tests

| Check | Result | Runtime |
| :--- | :--- | ---: |
| `ruff check .`, `ruff format --check .` | passed | < 1 s |
| `ty check` | passed, 0 diagnostics | 1 s |
| `pre-commit run --all-files` | all hooks passed | 3 s |
| `pytest -q` | 337 passed (320 before the phase) | 25 s |

| File | Tests | What |
| :--- | ---: | :--- |
| `test_platform_collab.py` | 7 | Invite, join, change roles and leave, keeping one owner. Share, view, fork and unshare, with the privacy switches, provenance and the leaderboard entry. Comments with mentions, replies, the five-minute edit window, deleting and hiding. Notification routes, quiet hours, and refusals of unknown kinds and zones. A market comment links to its page. Leaderboard ranking thresholds; the leaderboard job reads opted-in settlements only. Secrets without a master key answer 503. |
| `test_platform_delivery.py` | 7 | Each adapter signs and verifies the way its platform documents. The outbox retries, backs off and gives up, telling owners once an hour. A chat sender pairs on the page, then asks and resets. A brief is proposed, confirmed by a person, run and parsed. Webhooks are signed with their own secret. The MCP server is read-only and needs a token. Quiet hours hold a notice back. |
| `test_contribution_gates.py` | 3 | the name gate; no product surface names the reference project; no data file, and no table or code block over 60 lines, in the docs |
| `test_ui_catalogue.py` | changed | the new navigation keys; every key the new pages use is in the catalogue |

## Teams, Sharing, Comments, Leaderboards (tasks 81 to 84)

Built as designed (migrations 0021 and 0022; `teams.py`, `sharing.py`,
`comments.py`, `leaderboards.py`). The walk-through in a real browser:

- Ada signed up, confirmed a strategy and shared it with the rules and
  paper results showing.
- She entered the strategy on the leaderboards and commented on it.
- She invited Bo as an editor. Bo signed in, opened the emailed link and
  joined.
- Bo replied to Ada's comment and mentioned her.
- Ada saw "Notifications 1 unread" in the navigation. The notice read "bo…
  mentioned you" and linked to the strategy.

The public page opened in a browser with no session. The leaderboard job
ran on the stand-in and found nothing to rank: no entered strategy has a
settled paper position yet, and ranking needs 50.

## Channels, Briefs, Notifications, MCP, API (tasks 85 to 89)

Ada added an email channel and created a weekly brief sent to it. She
pressed Send now, and the brief arrived in the outbox with its `vp-brief`
block. In Detailed she added a webhook; its `whsec_` secret was shown once.
The MCP server was checked with raw JSON-RPC (initialize, tools/list,
tools/call, and 401 without a token), as recorded in the tests.

### Delivery per channel

On the stand-in database, 200 notices were routed to each destination at
three failure rates. Each attempt failed independently with probability
p, from a seeded simulated network. The retry schedule then ran to the
end. "Retried" counts messages delivered on a later attempt.

| p | Destination | Delivered | Dead | Attempts per delivered message | Retried |
| ---: | :--- | ---: | ---: | ---: | ---: |
| 0.0 | each of the six | 200 | 0 | 1.00 | 0 |
| 0.2 | discord | 200 | 0 | 1.22 | 31 |
| 0.2 | email channel | 200 | 0 | 1.21 | 37 |
| 0.2 | email (own address) | 200 | 0 | 1.20 | 35 |
| 0.2 | slack | 200 | 0 | 1.17 | 28 |
| 0.2 | telegram | 200 | 0 | 1.22 | 37 |
| 0.2 | webhook | 200 | 0 | 1.31 | 51 |
| 0.5 | discord | 193 | 7 | 1.69 | 74 |
| 0.5 | email channel | 194 | 6 | 1.88 | 96 |
| 0.5 | email (own address) | 194 | 6 | 1.85 | 93 |
| 0.5 | slack | 190 | 10 | 1.87 | 101 |
| 0.5 | telegram | 193 | 7 | 1.84 | 94 |
| 0.5 | webhook | 192 | 8 | 1.80 | 87 |

The expected dead share after five attempts is $p^5$:

- At p = 0.2 it is 0.03%, and none of the 1,200 messages died.
- At p = 0.5 it is 3.1%; 44 of 1,200 died (3.7%).

A receiver that stays down beyond the 156-minute retry window loses what
was sent to it. The Delivery page shows those losses as failed counts per
channel. The outbox sent at about 0.6 ms a message without network time
(1,200 to 2,325 sends a run). That is the database's cost per message,
not the platforms'.

These rates measure the retry machinery, not the platforms. Real rates
need bot tokens, a mail provider and receivers, which come with the cloud
deploy (task 34).

### Brief latency

| Measure | Result |
| :--- | :--- |
| Rendering a brief (median, max of five) | disagreements 0.7, 2.0 ms; settlements 1.3, 2.4 ms; weekly 0.7, 0.9 ms |
| Send now to email in the outbox, before the fix | 35, 40, 45, 45, 50 s (median 45 s) |
| The same, after the fix | 0.1 s in each of five runs |

Before the fix, the brief was rendered at once but waited for the
minute-by-minute delivery round. The brief job now queues a delivery round
itself. A scheduled brief still starts on the minute its schedule names.

### Sharing, forks and moderation

On the stand-in, over the tests' databases and the walk-through:

- 2 shares, 1 public view, and no forks outside the tests (the fork path
  is covered by `test_platform_collab.py`).
- 4 comments, none hidden or deleted.
- 2 invitations, both accepted; 2 workspaces with more than one member.

These are verification counts, not usage: there are no users yet. The
moderation load (hides per comment and per workspace-week) is recorded in
the activity feed (`comment_hidden`), so it can be read once people use
the platform.

## Contributions (task 90)

- `CONTRIBUTING.md` states the Developer Certificate of Origin and the
  checklists for signals, domain packs and domains.
- CI gained a `dco` job for pull requests that fails any commit without
  `Signed-off-by`.
- `test_contribution_gates.py` adds the name gate and the data-dump gate.
- Secrets are covered by the existing detect-secrets hook.

## Accessibility

axe-core at WCAG 2.2 AA found **zero violations on 18 page states**:

- Simple mode: strategy sharing before and after, team, team after
  inviting, team as the invited member, a reply with a mention,
  notifications, and delivery before and after a brief.
- Detailed mode: delivery, team, notifications, leaderboards and strategy.
- Dark theme: team, leaderboards and delivery.
- The public share page.

Controls that only an icon or a table position names carry labels:

- each route checkbox is named "Send {kind} notices to {route}";
- each role selector is named "Role of {email}";
- remove buttons name the person or channel.

Tables have captions. The unread count has a screen-reader suffix.

## Found and Fixed

| Fault | Fix |
| :--- | :--- |
| `/auth/me` read `select email from users`; the new team policy lets a member see teammates, so it could answer with another person's address | filtered by `vp_current_user_id()` |
| The keep-an-owner trigger would have blocked deleting a personal account | it refuses only while other members remain |
| The settlement notice named a field accounts do not have, and linked to `#paper`, which is not a page | generic text, link to `#strategies` |
| MCP without a token was refused 403 by the cross-site guard, not 401 | `/mcp` is exempt from the guard and answers 401 itself |
| Adding a webhook or a Telegram or Slack channel without `VP_MASTER_KEY` was a 500 | 503 with the reason |
| An unknown time zone in quiet hours or a brief was a 404 (`ZoneInfoNotFoundError` is a `KeyError`, so a `LookupError`) | 409 with the reason |
| A market comment's notice linked to `#market/<id>`, which needs the domain too | a market's subject is `<domain>:<id>` |
| One receiver outage sent the owners 44 "could not be delivered" notices | at most one an hour per kind and title (migration 0023) |
| Send now waited for the next delivery round: 45 s median | the brief job queues a round: 0.1 s |
| Everyone's own workspace is called Personal, so a member saw two workspaces with that name in the switcher | owners of a shared workspace still called Personal are asked to name it |

## Not Done

- No chat platform, mail provider or public webhook receiver was
  contacted. The adapters follow each platform's documented signing, and
  the tests check that. A real round trip needs tokens and the cloud
  deploy (task 34, flag F16).
- A chat `/ask` answers only with a key. Without one it replies that the
  workspace has no key (`CannotAsk`), as the tests check. Asking for real
  waits on the API key, like task 60.
- Leaderboards have no ranked entry, because no entered strategy has 50
  settled paper positions. Filling them takes weeks of paper trading.
- The screen-reader pass of task 47 still covers only the Phase 14 pages.
