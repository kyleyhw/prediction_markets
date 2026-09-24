# Collaboration and Delivery

Phase 18 of the plan. A workspace becomes a team; a strategy can be shown
to anyone and forked by anyone signed in; results carry conversations; and
research reaches people where they already are: their email, a chat, a
webhook, another agent. Every collaborative capability the reference
implementation has for one operator (`docs/vibe_trading.md` §§ 4.11 and 5)
is rebuilt here for many workspaces, from its description, never its code
or text (§ 9).

Until the cloud deploy (flag F16) all of it runs on the local stand-in:
mail lands in the outbox, chat platforms are reached only where a token is
configured, and the generic webhook is exercised against a local receiver.
Nothing here needs a model key except the in-chat questions, which queue a
research job like the page does and wait on the key as that does (task 60).

## Decisions, taken as proposed

| Question | Decision |
| :--- | :--- |
| What is a team? | A workspace with more than one member. Strategies, paper accounts, runs and conversations already belong to a workspace, so sharing within a team needs no new sharing model. |
| Roles | Owner, editor, viewer (migration 0001). Owners invite, change roles, remove, moderate and operate channels; editors change strategies and start work; viewers read and comment. A workspace always keeps at least one owner. |
| Invitations | By email, for seven days, accepted only by the invited address after signing in. The link is a 256-bit token stored as its hash, like every other credential. |
| Personal conversations | Stay personal: a conversation and the assistant's memory are the person's own even in a team (Phase 15). A strategy confirmed from one is shared. |
| Public links | Off until a person makes one. A link publishes a snapshot, not a live view: what the owner saw when publishing, refreshed daily and on demand. Default content: the rendering, the newest run card and the benchmark entry; P&L, the spec (and so forking) and the author's name are each opt-in. |
| Forks | A fork is a new strategy in the forker's workspace whose first version is the shared spec, with the source link, the spec hash and the time recorded as provenance. |
| Comments | On runs, markets and strategies; threads one level deep; `@` mentions of members; owners hide comments, authors delete their own; nothing is edited in place after five minutes. |
| Leaderboards | Opt-in per strategy; ranked by skill against the market on settled paper positions with a paired bootstrap interval; no rank below 50 settled positions; by domain and for 30, 90 days and all time; P&L is shown beside skill, never alone. |
| Channels | Email and a signed generic webhook first; Telegram, Slack and Discord through the same adapter interface, active only when a token is configured. An unknown sender in a direct chat gets a pairing code that a workspace owner approves on the page; pairing is never done in chat. |
| Briefs | Three templates with declared, typed variables. The assistant may propose a brief; only a person's confirmation on the page enables it. Briefs are computed from data, not written by a model, and end in a machine-readable block. |
| Notifications | In the app always; by email or a channel per person and kind; quiet hours defer delivery, never drop it. |
| MCP | Read-only tools over streamable HTTP, authenticated by the person's read-scoped API token. There is no order tool on this surface and there never will be. |
| Outgoing webhooks | Per workspace, per event kind, signed with a per-hook secret, delivered through the same outbox. |
| Contributions | The Developer Certificate of Origin (the decisions table's "yes, once contributions are invited"); CI checks sign-off on pull requests, secrets, market-data dumps in the docs, and the name gate. |

## Teams (task 81)

`invitations` holds the pending invitations of a workspace. Accepting is
done by `vp_accept_invitation`, a function running as the table owner
because the new member is not yet in the workspace whose rows it writes; it
checks the token, its expiry and that the signed-in person's address is the
invited one, and adds the membership. `vp_switch_workspace` moves a session
to another workspace its user belongs to, and nothing else. A trigger
refuses the change that would leave a workspace without an owner.
Teammates can read each other's address and nothing else of each other
(the `users_team` policy). Removing a member ends their sessions and tokens
in that workspace at once, since both resolve through the membership.

Every change is attributed: `activity` records who did what to which
object, appended by the same code that makes the change, readable by the
workspace. The audit chain (migration 0004) stays the operator's record.

## Sharing, forks and cards (task 82)

`shares` holds a strategy's public link: a random slug, the privacy
switches, and the published snapshot. `vp_share_view` is the only way the
public reaches it: it returns the snapshot of a live, unrevoked share and
counts the view, and it returns nothing else about the workspace. The
strategy card is the snapshot drawn as an SVG, for embedding.

## Comments (task 83)

`comments` is one table for every subject (`run`, `market`, `strategy`),
keyed by the subject's id as text. A mention is `@` followed by a member's
address's local part; each mention and each reply makes a notification.

## Leaderboards (task 84)

A platform job (`leaderboard`) reads the settled positions of opted-in
strategies through `vp_leaderboard_rows`, which returns, for opted-in
strategies only, each settlement's Brier score and the market's; it
computes the paired difference with a bootstrap interval per strategy,
domain and window, and stores the boards in `leaderboards`, which anyone
may read. A strategy below 50 settled positions is listed as "not yet
ranked" with its count.

## Channels (task 85)

A channel is an adapter plus an opaque target (an address, a chat id, a
URL). Adapters implement one interface, `send(target, text, data) ->
receipt` and, where the platform can call us, `inbound(headers, body) ->
message`, verifying the platform's own signature scheme first:

| Adapter | Outbound | Inbound | Verification |
| :--- | :--- | :--- | :--- |
| email | the mailer (outbox on the stand-in) | no | none |
| webhook | POST JSON | no | `X-VP-Signature: sha256=<HMAC of the body>` with the hook's secret |
| telegram | Bot API `sendMessage` | webhook updates | `X-Telegram-Bot-Api-Secret-Token` equals the secret set with the webhook |
| slack | incoming-webhook URL | Events API | `X-Slack-Signature` = `v0=` HMAC-SHA256 of `v0:<timestamp>:<body>`, timestamp within five minutes |
| discord | channel webhook URL | no | none |

Secrets are stored encrypted with the master key, as provider keys are
(migration 0008). Inbound messages go through the message bus: a known,
paired sender's text is a command (`/reset` starts a new conversation for
that chat; `/ask <question>` queues a read-only research turn charged to
the workspace's budget) or ignored; an unknown sender in a direct chat is
answered with a pairing code, valid for an hour, that an owner approves on
the page. `chat_sessions` maps each chat to one conversation, so a group
chat shares one session.

## Briefs (task 86)

| Template | Variables |
| :--- | :--- |
| `disagreements` | `threshold` points (default 10), `domains` (default all) |
| `settlements` | `days` (default 1) |
| `weekly` | none |

Each brief is rendered from the workspace's data at run time ("today" is
resolved in the brief's timezone then) and ends in a fenced block
`vp-brief` holding JSON with the brief's rows, which the Watch list
renders without reading the prose. A brief the assistant proposes is
stored disabled with `proposed_by = 'assistant'`; `POST
/api/briefs/{id}/confirm` from a browser session enables it and creates its
schedule. Delivery goes to the brief's channel through the outbox; the
brief job queues a delivery round at once, so a brief sent from the page
arrives in about a tenth of a second on the stand-in rather than at the
next minute's round (45 s median before this was added).

## The outbox (tasks 85 to 87, 89)

`outbox` holds every outgoing message: channel, payload, state (`queued`,
`sent`, `failed`, `dead`), attempts, the next attempt's time and the
provider's receipt. The `deliver` job sends what is due, backing off 1, 5,
30 and 120 minutes (a retry window of 156 minutes), then marks it dead and
notifies the owners, at most once an hour per kind and title (migration
0023): a receiver down during a burst would otherwise send one notice per
lost message. The Delivery page counts every failure per channel. Quiet
hours set the first attempt's time rather than dropping the message.
Messages or secrets that need the master key answer 503 when it is not set.

## Notifications (task 87)

`notifications` holds each person's notices (mention, reply, invitation,
fill, settlement, budget, halt, brief, health); `notification_prefs` their
choice of delivery per kind and their quiet hours. The page shows unread
notices and a count.

## MCP (task 88)

`vp/platform/mcp_server.py` mounts a streamable-HTTP MCP server at `/mcp` with the
official Python SDK. Every tool resolves the caller's token to a principal
and reads within that workspace: `search_markets`, `market_detail`,
`evidence` (a market's evidence at a cutoff), `forecasts`, `run_cards`,
`paper_status` and `signal_bench`. The test that no tool can place, sign or
send anything is a list of the tools' names checked against an allow-list.

## Public API and webhooks (task 89)

API tokens (Phase 13) authenticate the same JSON endpoints the page uses;
the rate limit of migration 0007 applies per token. Outgoing webhooks
(`webhooks`: workspace, URL, event kinds, secret) receive `run.finished`,
`paper.settled`, `brief.delivered` and `strategy.health` events through
the outbox. The OpenAPI page at `/docs` describes both.

## The pages

All in `vp/ui/static/app/` and hosted only; under `vp ui` they say so and
link Home. **Team** (`#team`): the workspaces a person belongs to with a
switch, members with roles (owners change them in place), invitations,
renaming (prompted while a shared workspace is still called Personal),
leaving, and the activity feed. **Notifications** (`#notifications`, with an
unread count in the navigation): the notices, and a table of kind by route
(email, each channel) with quiet hours. **Leaderboards**
(`#leaderboards/<domain>/<window>`): ranked entries with a verdict in
Simple and skill, advantage with its interval and P&L in Detailed; entries
still settling are listed apart. **Delivery** (`#delivery`, from Settings):
channels with sent and failed counts, pairing codes to approve, adding a
channel with per-kind help, briefs with their watch lists and switches, a
new-brief form whose schedule is chosen in words (a cron field in
Detailed), and in Detailed the webhooks and the tool server's address. A
strategy's page gains sharing switches with the public link, the
leaderboard entry and a comment thread; a market's page gains a thread
(subject `<domain>:<market id>`). Comment text is shown as plain text.

## Contributions (task 90)

`CONTRIBUTING.md` states the DCO and the signal and domain-pack checklists.
CI adds a job for pull requests that checks every commit carries
`Signed-off-by`, and tests that fail on a data dump in the docs (a table or
JSON block longer than the limit) and on the reference project's name
outside the files § 9 allows.
