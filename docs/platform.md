# The Platform

Phase 13 wraps the engine in everything needed to serve many people at
once. This page records what is built and why; the design it implements is
[product.md](product.md) for the shape and [scaling.md](scaling.md) for the
tenancy, storage and capacity decisions. The engine under `vp/` is
unchanged and knows nothing about any of it.

**Status.** Phase 13 is in progress. Built: configuration, the principal,
the database foundation and the tenancy boundary. Not built: the web
service, sign-in, the job queue, the market-data service, the evidence
collectors, deployment, budgets, observability. Each is a numbered task in
[the plan](../PROJECT_PLAN.md).

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
| `VP_DATABASE_URL` | yes | none | libpq connection string for the platform database |
| `VP_ENV` | no | `development` | `development`, `staging` or `production` |
| `VP_DATA_ROOT` | no | `data` | where the engine's Parquet files live |

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

- **The owner** runs migrations and the sign-up path. It owns the tables,
  so the policies do not apply to it. This is deliberate: creating a user,
  a workspace and that first membership all happen before any workspace
  context exists. Nothing else may use this connection.
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

## Running the Database Tests

The suite stays offline by default; the database tests skip unless both
connection strings are set. The first must own the tables, the second must
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
