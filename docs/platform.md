# The Platform

Phase 13 wraps the engine in everything needed to serve many people at
once. This page records what is built and why; the design it implements is
[product.md](product.md) for the shape and [scaling.md](scaling.md) for the
tenancy, storage and capacity decisions. The engine under `vp/` is
unchanged and knows nothing about any of it.

**Status.** Phase 13 is in progress, interface first (the plan's build
order). Built: configuration, the principal, the tenancy boundary, the web
service with email sign-in, sessions and API tokens, and the dashboard's
views behind sign-in, all verified in a real browser. Not built: the job
queue, the market-data service, the evidence collectors, budgets,
observability, per-workspace paper accounts, and the deploy, which comes
last (flag F16). Each is a numbered task in [the plan](../PROJECT_PLAN.md).

```bash
uv run vp db migrate          # as the owner: VP_MIGRATION_DATABASE_URL
uv run vp serve               # as vp_app: VP_DATABASE_URL, on :8000
```

In a web session the start-up hook starts Postgres, sets both URLs and
migrates, so `vp serve` works at once; sign-in links land in
`data/outbox/`.

## The Division

```ascii
vp/                 the engine: data roots, specs, cutoffs. No users, no HTTP.
vp/platform/        the platform: who is calling, where state lives, what it cost.
```

The first principle of the scaling design is that the engine never knows
who is calling, and the import direction enforces it: `vp/platform/` may
import the engine, and nothing in the engine may import the platform. That
is what lets one process serve one person today and a pool of workers
serve many later, and it is why per-user work is the platform's problem
rather than a parameter threaded through every engine function.

## Configuration

`vp.platform.config` is the only module that reads the environment. One
reader means the whole configuration surface fits on one page and a
missing setting fails at start rather than at the request that needs it.
`tests/test_config_gate.py` walks the package's syntax trees and fails if
a second reader appears.

Two engine knobs predate the platform and are listed as explicit
exceptions in that test: the per-host request spacing in `venues/_http.py`
and the kill-switch path in `live/controls.py`. They are command-line
conveniences rather than platform settings, and they fold into the config
module when the engine runs under the service. The test also checks that
each listed exception still reads the environment, so a stale entry cannot
quietly become a hole.

Two rules the types cannot express:

- **No secret has a default.** A missing `VP_DATABASE_URL` is a start-up
  error, never an empty string or a guess at localhost, because a default
  that happens to work in development is how a service reaches the wrong
  database in production.
- **Secrets do not print.** The database URL is excluded from the
  dataclass repr and reaches logs only through `redacted_database_url`, so
  a settings object in a traceback cannot leak a password.

| Variable | Required | Default | Meaning |
| :--- | :--- | :--- | :--- |
| `VP_DATABASE_URL` | yes | none | the service's own connection, as `vp_app` |
| `VP_ENV` | no | `development` | `development`, `staging` or `production` |
| `VP_DATA_ROOT` | no | `data` | where the engine's Parquet files live |
| `VP_PUBLIC_URL` | in production | `http://127.0.0.1:8000` | the origin people reach the service at; must be `https://` in production |
| `VP_MIGRATION_DATABASE_URL` | for `vp db migrate` | none | the owner's connection string, for migrations only |
| `VP_MAIL` | no | `outbox` | where sign-in emails go; production refuses `outbox` |

`VP_DATABASE_URL` is the service's own connection and must be `vp_app`.
Keeping the owner's URL in a separate variable, used only by
`vp db migrate`, means the web process never holds a credential that
bypasses tenancy. Production refuses plain HTTP, because session cookies
must be `Secure`, and refuses the outbox, because a link written to a file
on the server reaches nobody; so no production configuration can load
until a mail provider is chosen (flag F3).

## The Principal

Every request, job and command carries a `Principal`: a subject, how it
authenticated, the workspace it is acting in, and the roles it holds.

`attributable` is the field that matters. It says whether the subject
names an actual person, it is derived from the authentication method at
construction, and it cannot be passed in, because a caller-settable flag
is a caller-settable lie. A session and an API token both name a person:
the first follows a verified email, the second is minted by someone signed
in. Anonymous does not. Any control that needs a named human, such as an
approval or an audit entry, checks `attributable` and refuses rather than
quoting a label as if it were a person.

Roles are held **within** a workspace, so there is no ambient authority: a
principal holding `owner` with no workspace may do nothing at all. The
exception is `operator`, which is held on the platform rather than in a
workspace, and which by construction reaches no workspace's data: it is
the role that reads costs, sets budgets and trips the platform halt.

| Role | Read | Write | Membership |
| :--- | :--- | :--- | :--- |
| `viewer` | yes | no | no |
| `editor` | yes | yes | no |
| `owner` | yes | yes | yes |
| `operator` | no workspace data at all | | |

## Tenancy

Everything a person owns belongs to a workspace, every tenant table
carries `workspace_id`, and Postgres row-level security answers every
query against the workspace set on the connection. The property this buys
is worth stating as the test does: **a query that forgets its filter
returns nothing, rather than someone else's data.** An unset workspace
matches no row, because a comparison against NULL is never true, so the
failure direction is closed.

Two database roles, and the guarantee depends on the difference:

- **The owner** runs migrations and nothing else. It owns the tables, so
  the policies do not apply to it. The service never connects as the
  owner: signing up, which must create a user, a workspace and a
  membership before any workspace context exists, happens inside five
  narrow database functions instead (see Sign-in and the Web Service).
- **`vp_app`** owns nothing and is subject to every policy. Everything
  else connects as this role. It must never be a superuser, which bypasses
  row-level security unconditionally; the test fixture asserts both.

The context is set with `set_config(..., true)`, local to the transaction,
so a pooled connection cannot carry one workspace into the next request.

### The savepoint hazard

This is the part that would have been a silent hole, and it is why
`connect` opens connections in autocommit mode.

A psycopg connection that is not in autocommit mode opens a transaction on
its first statement and holds it open. A `conn.transaction()` block on
such a connection is then a **savepoint inside that transaction**, not a
transaction of its own. Two consequences, neither of which raises
anything:

1. A workspace set with `set_config(..., true)` lives until the outer
   transaction ends, so the next request on that connection inherits it.
2. Writes sit uncommitted in the outer transaction and vanish when the
   connection closes.

Both were observed while building this: the migration runner left its
connection inside an open transaction, and the seeding that followed
appeared to succeed while committing nothing. The fix is structural rather
than careful coding. Connections are opened in autocommit mode, every unit
of work is an explicit transaction block, and both `migrate` and
`tenant_session` refuse a connection that is already inside a transaction
instead of quietly degrading to a savepoint.

### Migrations

Numbered SQL files applied in filename order, each in its own transaction,
each recorded with the SHA-256 of its bytes. A file that changes after it
has been applied is refused, because at that point the database and the
repository disagree about what the schema is and only one of them knows.
The ledger table is the platform's own bookkeeping and `vp_app` is
explicitly revoked from it.

`0001_foundation.sql` creates workspaces, users and memberships, their
policies, and the `vp_app` role. Role creation is idempotent and raises a
message naming the manual step if the connection may not create roles, as
on a managed host where the operator provisions roles out of band.

## Sign-in and the Web Service

`vp serve` runs one FastAPI application over the unchanged engine
(`vp/platform/web.py`). Every request resolves to a `Principal`, from a
session cookie or a bearer token, and every route that reads anything
requires one that names a person.

### Crossing the tenancy boundary, narrowly

Signing in has to create rows before any workspace exists, which the
policies refuse. The obvious fix, giving the web process the owner's
credentials for that step, would put a role that bypasses tenancy inside
the process most exposed to the internet. Instead, migration 0002 defines
five `SECURITY DEFINER` functions, which run as their owner and are the
only code that crosses the boundary:

| Function | Does |
| :--- | :--- |
| `vp_auth_request_sign_in` | records a sign-in token for an address, at most five per address per fifteen minutes |
| `vp_auth_sign_in` | exchanges an unused, unexpired token for a thirty-day session, creating the user and a personal workspace on first use |
| `vp_auth_resolve_session` | who a session belongs to, only while its membership exists |
| `vp_auth_end_session` | revokes a session |
| `vp_auth_resolve_token` | who an API token belongs to, only while its membership exists |

Two properties follow. **No function makes a session for a named user**:
the only way to one is a token that was sent to that user's address. And
**every limit is fixed in the function**, not passed in, so a caller cannot
lengthen a session or loosen the rate. Each function sets its own
`search_path` and uses no dynamic SQL. The sign-in and session tables have
row-level security with no policy and no grants to `vp_app`, so the
functions are the only way in. Removing a membership ends every session
and token in that workspace at once, because resolution joins on it.

### Secrets

The link's token, the session cookie and an API token are each 256 random
bits, given to the person once and stored as a SHA-256. A plain hash is
right here, not a slow password hash: these are random values, not
passwords a person chose, so there is nothing to guess. The session
cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` whenever the public URL
is HTTPS.

### Five rules the service enforces

1. **It connects only as a role row-level security binds.** At start it
   refuses a superuser, a role that may bypass row-level security, or the
   tables' owner. The tenancy suite proves isolation for `vp_app`; running
   as anything else would make it prove nothing.
2. **State changes come from its own pages.** A request that changes
   anything and is not bearer-authenticated must carry
   `Sec-Fetch-Site: same-origin` or a matching `Origin`. Without this,
   another site could post a form that signs a visitor out, or signs them
   into an account the attacker controls. Bearer requests are exempt,
   since browsers never add that header themselves.
3. **Opening a link does not sign in.** The emailed link opens a page with
   one button; only the button's `POST` spends the token. Mail scanners
   fetch every link in a message, and a link that signed in on `GET`
   would be spent before the person clicked.
4. **Secrets stay out of logs and referrers.** A log filter replaces every
   `token=` value in the access log, and `Referrer-Policy: same-origin`
   keeps the link's URL from being sent to any other site.
5. **Nothing personal stays in the browser's cache.** Every response
   except the fonts carries `Cache-Control: no-store`.

API tokens are managed only from a signed-in browser, so a leaked token
cannot mint more. A read token acts as a viewer; a write token acts with
its owner's role, never more.

### What the browser found

The request tests drive the service with `TestClient`, which sends
whatever headers a test chooses. Driving a real Chromium through the
whole flow found two faults they could not:

- **`Referrer-Policy: no-referrer` broke sign-in.** Under that policy
  Chromium sends `Origin: null` on the page's own form posts, which rule 2
  refused. The policy is now `same-origin`, and the check trusts
  `Sec-Fetch-Site: same-origin` first, which browsers always send and
  pages cannot forge.
- **The dashboard outlived sign-out.** Without a cache directive, Chromium
  served the dashboard page from its cache after sign-out without asking
  the server. The data calls were refused, so nothing leaked, but a shared
  computer showed a signed-in page. Rule 5 came from this.

The walk-through (sign-in page, emailed link, confirm button, dashboard
with the account panel, sign-out, and back to sign-in on revisiting)
passes, and the access log carries the token only as `[redacted]`.

### Known gaps, all scheduled

- **The data root is shared.** The views read the same data root for
  everyone signed in. On a development machine with one person that is
  harmless; per-workspace paper accounts and runs land with tasks 30 and
  37, before anyone else uses the service.
- **The page still speaks to developers.** Its empty states say to run
  `vp` commands, and its footer shows the server's data path. Replacing
  these is the friendly-interface work that comes next (tasks 39 to 47).
- **No per-address-and-IP rate limit** beyond five links per address per
  fifteen minutes; request limits come with observability (task 36).
- **No sweep of expired tokens and sessions** yet; it becomes a scheduled
  job when the queue exists (task 31).

## Running the Database Tests

The suite stays offline by default; the database tests skip unless both
connection strings are set. In a web session the start-up hook sets them,
so `uv run pytest -q` runs everything. The first must own the tables, the second must
be `vp_app`. Pointing both at the same role would make every assertion
pass for the wrong reason, so the fixture checks they differ and that the
second is not a superuser.

```bash
createdb vp_dev
VP_TEST_DATABASE_URL='postgresql:///vp_dev?host=/var/run/postgresql&user=postgres' \
VP_TEST_APP_DATABASE_URL='postgresql:///vp_dev?host=/var/run/postgresql&user=vp_app' \
uv run pytest -q
```

## Measured

**Venue reachability (flag F1), 2026-09-21, from the development
container.** All three hosts answered: Gamma search, the CLOB markets
endpoint and the Data API each returned HTTP 200 in under 0.6 s. This is
the technical half of F1 only, and it was measured from this container,
**not** from the region the platform will run in. The check that matters
is the same probe from the deployed region, together with the reading of
the venue's terms on automated access, data storage and commercial use;
both are tasks of this phase and neither is done.
