-- Signals and the public benchmark (plan, Phase 16; docs/signals.md).
--
-- The platform's own data, the same for everyone: the latest bench of each
-- domain, and each week's frozen questions with every configuration's
-- sealed forecasts. A sealed entry's salt and payload stay in the table
-- until the week is revealed; the service shows them only then, so what
-- is public before resolution is the commitment alone.

create table signal_bench (
    domain     text primary key,
    result     jsonb not null,
    created_at timestamptz not null default now()
);

create table benchmark_weeks (
    id         uuid primary key default gen_random_uuid(),
    week       text not null unique,
    body       jsonb not null,
    hash       text not null check (hash ~ '^[0-9a-f]{64}$'),
    frozen_at  timestamptz not null,
    scored_at  timestamptz
);

create table benchmark_entries (
    week_id     uuid not null references benchmark_weeks (id) on delete cascade,
    config      text not null,
    commitment  text not null check (commitment ~ '^[0-9a-f]{64}$'),
    salt        text not null,
    payload     text not null,
    revealed_at timestamptz,
    score       jsonb,
    primary key (week_id, config)
);

-- A sealed entry never changes before it is revealed.
create or replace function vp_benchmark_sealed() returns trigger
    language plpgsql
as $$
begin
    if new.commitment is distinct from old.commitment
       or new.salt is distinct from old.salt
       or new.payload is distinct from old.payload then
        raise exception 'a committed benchmark entry is never changed';
    end if;
    return new;
end
$$;
create trigger benchmark_entries_sealed before update on benchmark_entries
    for each row execute function vp_benchmark_sealed();

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
                      'reconcile', 'sweep', 'sample_cycle', 'sample_settle',
                      'signal_bench', 'benchmark_freeze', 'benchmark_score') then
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

-- Freeze on Monday just after midnight UTC, score daily, bench weekly.
insert into schedules (name, kind, payload, cron, timezone, next_run_at) values
    ('benchmark-freeze', 'benchmark_freeze', '{}', '5 0 * * 1', 'UTC', now()),
    ('benchmark-score', 'benchmark_score', '{}', '15 6 * * *', 'UTC', now()),
    ('signal-bench', 'signal_bench', '{}', '30 3 * * 0', 'UTC', now());
