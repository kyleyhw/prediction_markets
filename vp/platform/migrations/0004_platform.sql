-- Migration 0004: the platform's own state (plan, Phase 13, tasks 30 to 36).
--
-- Two kinds of table, and the difference decides the policy:
--
--   * Per-workspace: paper accounts and their ledgers, forecasts, runs,
--     jobs, schedules, spend, budgets, provider keys. Each carries
--     `workspace_id` and is protected by row-level security exactly as the
--     tables of migration 0001 are, so a query that forgets its filter
--     returns nothing.
--   * Shared: what the platform computes or observes once for everyone and
--     that holds nothing about any person: the market registry, quotes,
--     resolutions, the forecast memo of the statistical forecasters, and
--     the evidence index. No policy; `vp_app` reads them, and writes them
--     only from the ingest and worker processes.
--
-- Work that must cross the tenancy boundary (a worker claiming the next job
-- from any workspace, the scheduler firing a workspace's schedule, the
-- audit chain) goes through the SECURITY DEFINER functions at the end, as
-- sign-in does in migration 0002. Each fixes its own limits, sets its own
-- search_path, and returns only what the caller needs.
--
-- Strategies, their versions and chat channels are not created here: the
-- strategy spec is Phase 15's design (`docs/strategies.md` comes before any
-- code) and channels are Phase 18's.

-- ------------------------------------------------------------ partitions

-- Monthly range partitions for the tables that grow without bound. A
-- default partition catches any row outside the created range, so an
-- insert never fails for want of a partition; `vp_ensure_partitions`,
-- run daily by the scheduler, keeps the next months ahead of time.
--
-- A partition is a table of its own, and row-level security on the parent
-- does not follow a query that names the partition directly. The default
-- privileges of migration 0001 would give `vp_app` every new partition,
-- so each per-workspace partition has its privileges taken back as it is
-- created: `vp_app` reaches the rows only through the parent, where the
-- policy applies.

create or replace function vp_ensure_partitions(p_months int)
    returns int
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    t text;
    m date;
    made int := 0;
    name text;
begin
    if p_months < 1 or p_months > 24 then
        raise exception 'p_months must be between 1 and 24';
    end if;
    -- A fixed list: the only dynamic SQL here names these tables and nothing
    -- a caller supplies.
    foreach t in array array['ledger_entries', 'forecasts', 'quotes'] loop
        for i in 0 .. p_months loop
            m := (date_trunc('month', now()) + make_interval(months => i))::date;
            name := format('%s_%s', t, to_char(m, 'YYYYMM'));
            if to_regclass(name) is null then
                execute format(
                    'create table %I partition of %I for values from (%L) to (%L)',
                    name, t, m, (m + interval '1 month')::date
                );
                if t <> 'quotes' then
                    execute format('revoke all on table %I from vp_app', name);
                end if;
                made := made + 1;
            end if;
        end loop;
    end loop;
    return made;
end
$$;

-- --------------------------------------------------------- paper accounts

create table paper_accounts (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    name         text not null check (length(trim(name)) between 1 and 100),
    domains      text[] not null check (cardinality(domains) >= 1),
    forecasters  text[] not null check (cardinality(forecasters) >= 1),
    initial_cash numeric not null default 1000 check (initial_cash > 0),
    created_by   uuid references users (id) on delete set null,
    created_at   timestamptz not null default now(),
    unique (workspace_id, name)
);

-- The ledger of `vp/paper/ledger.py`, one hash chain per account. `entry`
-- is the entry exactly as hashed (sequence, time, kind, data, previous
-- hash), so `Ledger.verify` runs unchanged over an export. `ledger_heads`
-- holds each chain's newest sequence and hash; an append locks the head
-- row, so two writers to one account queue rather than fork the chain.
create table ledger_heads (
    account_id   uuid primary key references paper_accounts (id) on delete cascade,
    workspace_id uuid not null references workspaces (id) on delete cascade,
    seq          bigint not null,
    hash         text not null
);

create table ledger_entries (
    account_id   uuid not null,
    workspace_id uuid not null,
    seq          bigint not null check (seq >= 0),
    at           timestamptz not null,
    kind         text not null,
    entry        jsonb not null,
    hash         text not null,
    primary key (account_id, seq, at)
) partition by range (at);
create table ledger_entries_default partition of ledger_entries default;
create index ledger_entries_account_idx on ledger_entries (account_id, seq);

-- ------------------------------------------------------------- forecasts

create table forecasts (
    id           bigint generated always as identity,
    workspace_id uuid not null default vp_current_workspace(),
    account_id   uuid,
    job_id       uuid,
    forecaster   text not null,
    market_id    text,
    domain       text,
    p_hat        double precision not null check (p_hat between 0 and 1),
    cutoff       timestamptz not null,
    cost_usd     numeric not null default 0,
    memo_key     text,
    record       jsonb not null,
    at           timestamptz not null default now(),
    primary key (id, at)
) partition by range (at);
create table forecasts_default partition of forecasts default;
create index forecasts_workspace_idx on forecasts (workspace_id, at desc);
create index forecasts_market_idx on forecasts (workspace_id, market_id);

-- Shared: a statistical forecaster's answer depends only on the market,
-- the snapshot and the forecaster's version, so it is computed once for
-- every workspace that asks. Language-model forecasts with a person's own
-- prompt are private and never memoised.
create table forecast_memo (
    memo_key   text primary key,
    forecaster text not null,
    market_id  text,
    record     jsonb not null,
    created_at timestamptz not null default now()
);

-- ------------------------------------------------------------------ runs

create table runs (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    kind         text not null check (kind in ('backtest', 'leakage')),
    job_id       uuid,
    config       jsonb not null,
    results      jsonb,
    summary      text,
    artifacts    text,
    created_by   uuid references users (id) on delete set null,
    created_at   timestamptz not null default now()
);
create index runs_workspace_idx on runs (workspace_id, created_at desc);

-- ------------------------------------------------------------------ jobs

create table jobs (
    id               uuid primary key default gen_random_uuid(),
    workspace_id     uuid references workspaces (id) on delete cascade,
    created_by       uuid references users (id) on delete set null,
    kind             text not null,
    payload          jsonb not null default '{}'::jsonb,
    idempotency_key  text,
    priority         int not null default 100,
    state            text not null default 'queued'
                     check (state in ('queued', 'running', 'succeeded', 'failed',
                                      'dead', 'cancelled')),
    run_after        timestamptz not null default now(),
    attempts         int not null default 0,
    max_attempts     int not null default 3 check (max_attempts between 1 and 10),
    lease_token      uuid,
    lease_until      timestamptz,
    heartbeat_at     timestamptz,
    worker           text,
    progress         jsonb not null default '{}'::jsonb,
    result           jsonb,
    error            text,
    reserved_usd     numeric not null default 0,
    cancel_requested boolean not null default false,
    created_at       timestamptz not null default now(),
    started_at       timestamptz,
    finished_at      timestamptz
);
create unique index jobs_idempotency_idx on jobs
    (coalesce(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid), kind, idempotency_key)
    where idempotency_key is not null;
create index jobs_claim_idx on jobs (kind, priority, run_after) where state = 'queued';
create index jobs_workspace_idx on jobs (workspace_id, created_at desc);
create index jobs_running_idx on jobs (lease_until) where state = 'running';

-- A worker waiting for work wakes on this rather than polling.
create or replace function vp_jobs_notify() returns trigger
    language plpgsql
as $$
begin
    perform pg_notify('vp_jobs', new.kind);
    return new;
end
$$;
create trigger jobs_notify after insert on jobs
    for each row execute function vp_jobs_notify();

create table schedules (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid references workspaces (id) on delete cascade,
    created_by   uuid references users (id) on delete set null,
    name         text not null check (length(trim(name)) between 1 and 100),
    kind         text not null,
    payload      jsonb not null default '{}'::jsonb,
    cron         text not null,
    timezone     text not null default 'UTC',
    enabled      boolean not null default true,
    next_run_at  timestamptz not null,
    last_run_at  timestamptz
);
create unique index schedules_name_idx on schedules
    (coalesce(workspace_id, '00000000-0000-0000-0000-000000000000'::uuid), name);

-- Operator switches: a drained job kind is not claimed.
create table ops_flags (
    name       text primary key,
    value      jsonb not null,
    set_at     timestamptz not null default now()
);

-- ------------------------------------------------------ budgets and spend

create table budgets (
    workspace_id      uuid primary key references workspaces (id) on delete cascade,
    monthly_limit_usd numeric not null default 5 check (monthly_limit_usd >= 0),
    updated_at        timestamptz not null default now()
);

create table spend (
    id                 bigint generated always as identity primary key,
    workspace_id       uuid not null default vp_current_workspace()
                       references workspaces (id) on delete cascade,
    job_id             uuid,
    kind               text not null check (kind in ('reservation', 'charge', 'release')),
    forecaster         text,
    domain             text,
    model              text,
    input_tokens       bigint not null default 0,
    output_tokens      bigint not null default 0,
    cache_read_tokens  bigint not null default 0,
    cache_write_tokens bigint not null default 0,
    usd                numeric not null,
    at                 timestamptz not null default now()
);
create index spend_workspace_idx on spend (workspace_id, at);

-- A person's own provider key, under envelope encryption: a fresh data key
-- encrypts the secret, and the master key (the key-management service's
-- stand-in) encrypts the data key. Neither plaintext is stored.
create table provider_keys (
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    provider     text not null check (provider in ('anthropic')),
    ciphertext   bytea not null,
    wrapped_key  bytea not null,
    key_version  int not null,
    hint         text not null,
    created_by   uuid references users (id) on delete set null,
    created_at   timestamptz not null default now(),
    primary key (workspace_id, provider)
);

-- -------------------------------------------------------- halts and audit

create table halts (
    id           uuid primary key default gen_random_uuid(),
    scope        text not null check (scope in ('platform', 'workspace')),
    workspace_id uuid references workspaces (id) on delete cascade,
    reason       text not null,
    set_by       text not null,
    set_at       timestamptz not null default now(),
    cleared_by   text,
    cleared_at   timestamptz,
    check ((scope = 'platform') = (workspace_id is null))
);

-- The platform's own hash chain: halts, budget changes, key changes,
-- archives. Same entry shape and hashing as the paper ledger.
create table audit_entries (
    seq   bigint primary key check (seq >= 0),
    at    timestamptz not null,
    kind  text not null,
    entry jsonb not null,
    hash  text not null
);

-- ----------------------------------------------------- shared market data

create table tracked_markets (
    market_id    text primary key,
    condition_id text,
    domain       text not null,
    question     text not null,
    event_title  text,
    tokens       text[] not null,
    end_date     timestamptz,
    record       jsonb not null,
    first_seen   timestamptz not null default now(),
    last_seen    timestamptz not null default now(),
    closed       boolean not null default false
);
create index tracked_markets_domain_idx on tracked_markets (domain) where not closed;

-- One row per token per minute, and on every top-of-book change for markets
-- a paper account holds.
create table quotes (
    token_id   text not null,
    market_id  text not null,
    minute     timestamptz not null,
    bid        double precision,
    ask        double precision,
    bid_size   double precision,
    ask_size   double precision,
    changed_at timestamptz not null,
    primary key (token_id, minute)
) partition by range (minute);
create table quotes_default partition of quotes default;

create table resolutions (
    condition_id text primary key,
    market_id    text,
    status       text not null,
    payouts      jsonb,
    winner_index int,
    source       text not null,
    resolved_at  timestamptz,
    observed_at  timestamptz not null default now()
);

create table evidence_captures (
    id          bigint generated always as identity primary key,
    source      text not null,
    domain      text,
    subject     text not null,
    captured_at timestamptz not null,
    object_key  text not null,
    rows        int not null,
    bytes       bigint not null
);
create index evidence_captures_source_idx on evidence_captures (source, captured_at desc);

-- ---------------------------------------------------------------- policies

alter table paper_accounts enable row level security;
create policy paper_accounts_tenant on paper_accounts
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

alter table ledger_heads enable row level security;
create policy ledger_heads_tenant on ledger_heads
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

alter table ledger_entries enable row level security;
create policy ledger_entries_tenant on ledger_entries
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

alter table forecasts enable row level security;
create policy forecasts_tenant on forecasts
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

alter table runs enable row level security;
create policy runs_tenant on runs
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- A workspace sees and enqueues its own jobs; platform jobs (no workspace)
-- are reached only through the functions below.
alter table jobs enable row level security;
create policy jobs_tenant on jobs
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

alter table schedules enable row level security;
create policy schedules_tenant on schedules
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

alter table budgets enable row level security;
create policy budgets_read on budgets
    for select using (workspace_id = vp_current_workspace());

alter table spend enable row level security;
create policy spend_tenant on spend
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

alter table provider_keys enable row level security;
create policy provider_keys_tenant on provider_keys
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- Platform-only: reached through functions, never directly.
alter table halts enable row level security;
alter table audit_entries enable row level security;
alter table ops_flags enable row level security;
revoke all on table halts, audit_entries, ops_flags from vp_app;
revoke all on table ledger_entries_default, forecasts_default from vp_app;
grant usage on all sequences in schema public to vp_app;

-- ------------------------------------------------------------- functions

-- Whether work for a workspace (or, with NULL, for the platform) may run.
create or replace function vp_halted(p_workspace uuid)
    returns boolean
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select exists (
        select 1 from halts
        where cleared_at is null
          and (scope = 'platform' or workspace_id = p_workspace)
    )
$$;

-- Claim the next job of the given kinds: highest priority, then oldest,
-- skipping any another worker holds. Nothing is claimed while the platform
-- is halted, from a halted workspace, or of a drained kind.
create or replace function vp_jobs_claim(p_kinds text[], p_worker text, p_lease_seconds int)
    returns setof jobs
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    picked jobs;
begin
    if p_lease_seconds < 5 or p_lease_seconds > 3600 then
        raise exception 'lease must be between 5 and 3600 seconds';
    end if;
    if vp_halted(null) then
        return;
    end if;
    select * into picked from jobs j
    where j.state = 'queued'
      and j.kind = any (p_kinds)
      and j.run_after <= now()
      and not exists (select 1 from ops_flags f where f.name = 'drain:' || j.kind)
      and (j.workspace_id is null or not vp_halted(j.workspace_id))
    order by j.priority, j.run_after, j.created_at
    for update skip locked
    limit 1;
    if not found then
        return;
    end if;
    update jobs set
        state = 'running',
        attempts = attempts + 1,
        lease_token = gen_random_uuid(),
        lease_until = now() + make_interval(secs => p_lease_seconds),
        heartbeat_at = now(),
        worker = left(p_worker, 200),
        started_at = coalesce(started_at, now())
    where id = picked.id
    returning * into picked;
    return next picked;
end
$$;

-- Renew a lease and record progress. Returns 'ok', 'cancel' when someone
-- asked for the job to stop, or 'lost' when the lease is no longer this
-- worker's (it expired and the job was taken back).
create or replace function vp_jobs_heartbeat(
    p_id uuid, p_token uuid, p_progress jsonb, p_lease_seconds int
)
    returns text
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    wants_cancel boolean;
begin
    update jobs set
        lease_until = now() + make_interval(secs => least(greatest(p_lease_seconds, 5), 3600)),
        heartbeat_at = now(),
        progress = coalesce(p_progress, progress)
    where id = p_id and lease_token = p_token and state = 'running'
    returning cancel_requested into wants_cancel;
    if not found then
        return 'lost';
    end if;
    return case when wants_cancel then 'cancel' else 'ok' end;
end
$$;

-- Finish a job. A failure with attempts left goes back on the queue after
-- an exponential delay; the last failure is dead (the dead-letter state).
create or replace function vp_jobs_finish(
    p_id uuid, p_token uuid, p_state text, p_result jsonb, p_error text
)
    returns text
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    j jobs;
begin
    if p_state not in ('succeeded', 'failed', 'cancelled') then
        raise exception 'unknown final state %', p_state;
    end if;
    select * into j from jobs
    where id = p_id and lease_token = p_token and state = 'running'
    for update;
    if not found then
        return 'lost';
    end if;
    if p_state = 'failed' and j.attempts < j.max_attempts then
        update jobs set state = 'queued', lease_token = null, lease_until = null,
            error = left(p_error, 4000),
            run_after = now() + make_interval(secs => 30 * power(2, j.attempts - 1))
        where id = p_id;
        return 'retry';
    end if;
    update jobs set
        state = case when p_state = 'failed' then 'dead' else p_state end,
        result = p_result,
        error = left(p_error, 4000),
        lease_token = null,
        lease_until = null,
        finished_at = now(),
        progress = case when p_state = 'succeeded'
                        then progress || '{"fraction": 1}'::jsonb else progress end
    where id = p_id;
    return case when p_state = 'failed' then 'dead' else p_state end;
end
$$;

-- Take back jobs whose worker stopped renewing its lease: requeued while
-- attempts remain, dead after. Returns how many were taken back.
create or replace function vp_jobs_reap()
    returns int
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    n int;
begin
    with lost as (
        update jobs set
            state = case when attempts < max_attempts then 'queued' else 'dead' end,
            lease_token = null,
            lease_until = null,
            error = 'lease expired: the worker stopped renewing it',
            finished_at = case when attempts < max_attempts then null else now() end
        where state = 'running' and lease_until < now()
        returning 1
    )
    select count(*) into n from lost;
    return n;
end
$$;

-- Platform work (ingest, data refresh, maintenance) has no workspace.
create or replace function vp_jobs_enqueue_platform(
    p_kind text, p_payload jsonb, p_idempotency_key text, p_priority int, p_run_after timestamptz
)
    returns uuid
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    new_id uuid;
begin
    if p_kind not in ('scheduler', 'snapshot', 'dataset', 'evidence', 'partitions',
                      'reconcile', 'sweep') then
        raise exception 'not a platform job kind: %', p_kind;
    end if;
    insert into jobs (kind, payload, idempotency_key, priority, run_after)
    values (p_kind, coalesce(p_payload, '{}'::jsonb), p_idempotency_key,
            coalesce(p_priority, 100), coalesce(p_run_after, now()))
    on conflict do nothing
    returning id into new_id;
    return new_id;
end
$$;

-- The schedules due now, for the scheduler to fire. Returns what it needs
-- to compute the next fire time, nothing about the workspace's data.
create or replace function vp_schedules_due()
    returns table (id uuid, cron text, timezone text, next_run_at timestamptz)
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select s.id, s.cron, s.timezone, s.next_run_at from schedules s
    where s.enabled and s.next_run_at <= now()
    order by s.next_run_at
    limit 500
$$;

-- Fire one schedule: enqueue its job (once per fire time, whatever happens
-- to the scheduler) and move it to its next fire time.
create or replace function vp_schedules_fire(p_id uuid, p_fired_at timestamptz, p_next timestamptz)
    returns uuid
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    s schedules;
    new_id uuid;
begin
    select * into s from schedules where id = p_id and enabled for update;
    if not found then
        return null;
    end if;
    if p_next <= p_fired_at then
        raise exception 'the next fire time must be after this one';
    end if;
    insert into jobs (workspace_id, created_by, kind, payload, idempotency_key, priority)
    values (s.workspace_id, s.created_by, s.kind, s.payload,
            'schedule:' || s.id || ':' || to_char(p_fired_at at time zone 'UTC',
                                                  'YYYYMMDD"T"HH24MISS'), 100)
    on conflict do nothing
    returning id into new_id;
    update schedules set last_run_at = p_fired_at, next_run_at = p_next where id = p_id;
    return new_id;
end
$$;

-- Append to the audit chain. The lock serialises writers so the chain
-- cannot fork; the hash is computed by the caller over the same canonical
-- JSON as the paper ledger and checked here for shape only.
create or replace function vp_audit_append(p_entry jsonb, p_hash text)
    returns bigint
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    head audit_entries;
    expected_seq bigint;
    expected_prev text;
begin
    perform pg_advisory_xact_lock(hashtext('vp_audit'));
    select * into head from audit_entries order by seq desc limit 1;
    expected_seq := coalesce(head.seq + 1, 0);
    expected_prev := coalesce(head.hash, repeat('0', 64));
    if (p_entry ->> 'seq')::bigint <> expected_seq or p_entry ->> 'prev' <> expected_prev then
        raise exception 'audit entry out of order: expected seq % after %', expected_seq, expected_prev
            using errcode = '40001';
    end if;
    if p_hash !~ '^[0-9a-f]{64}$' then
        raise exception 'malformed hash';
    end if;
    insert into audit_entries (seq, at, kind, entry, hash)
    values (expected_seq, (p_entry ->> 'at')::timestamptz, p_entry ->> 'kind', p_entry, p_hash);
    return expected_seq;
end
$$;

create or replace function vp_audit_head()
    returns table (seq bigint, hash text)
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select a.seq, a.hash from audit_entries a order by a.seq desc limit 1
$$;

revoke all on function vp_ensure_partitions(int), vp_halted(uuid),
    vp_jobs_claim(text[], text, int), vp_jobs_heartbeat(uuid, uuid, jsonb, int),
    vp_jobs_finish(uuid, uuid, text, jsonb, text), vp_jobs_reap(),
    vp_jobs_enqueue_platform(text, jsonb, text, int, timestamptz),
    vp_schedules_due(), vp_schedules_fire(uuid, timestamptz, timestamptz),
    vp_audit_append(jsonb, text), vp_audit_head() from public;
grant execute on function vp_ensure_partitions(int), vp_halted(uuid),
    vp_jobs_claim(text[], text, int), vp_jobs_heartbeat(uuid, uuid, jsonb, int),
    vp_jobs_finish(uuid, uuid, text, jsonb, text), vp_jobs_reap(),
    vp_jobs_enqueue_platform(text, jsonb, text, int, timestamptz),
    vp_schedules_due(), vp_schedules_fire(uuid, timestamptz, timestamptz),
    vp_audit_append(jsonb, text), vp_audit_head() to vp_app;

select vp_ensure_partitions(2);
