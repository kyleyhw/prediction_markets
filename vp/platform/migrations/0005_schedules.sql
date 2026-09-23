-- Migration 0005: the platform's own schedules and the expiry sweep.
--
-- The schedules the scheduler fires for everyone. Times are UTC; a
-- workspace's own schedules (its paper cycles and settlements) are created
-- when it starts paper trading, in its own time zone.
--
--   partitions   daily      keep next months' partitions created ahead
--   sweep        daily      forget expired sign-in links and sessions, and
--                           finished jobs older than ninety days
--   reconcile    hourly     resolutions the live feed may have missed
--   dataset      daily      each domain's resolved dataset, a new version
--   evidence     hourly     the evidence collectors (task 33)
--
-- Snapshots are taken by the market-data service, not by a schedule; the
-- `snapshot` job remains for an on-demand refresh and as the fallback.

insert into schedules (name, kind, payload, cron, timezone, next_run_at) values
    ('partitions', 'partitions', '{}', '10 3 * * *', 'UTC', now()),
    ('sweep', 'sweep', '{}', '20 3 * * *', 'UTC', now()),
    ('reconcile', 'reconcile', '{}', '5 * * * *', 'UTC', now()),
    ('dataset-cs2', 'dataset', '{"domain": "cs2", "history": true}', '30 4 * * *', 'UTC', now()),
    ('dataset-weather', 'dataset', '{"domain": "weather", "history": false}', '40 4 * * *', 'UTC', now()),
    ('dataset-epl', 'dataset', '{"domain": "epl", "history": true}', '50 4 * * *', 'UTC', now()),
    ('evidence', 'evidence', '{}', '15 * * * *', 'UTC', now());

create or replace function vp_platform_sweep()
    returns table (sign_in_tokens bigint, sessions bigint, jobs bigint)
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    a bigint;
    b bigint;
    c bigint;
begin
    with gone as (delete from sign_in_tokens where expires_at < now() - interval '1 day' returning 1)
    select count(*) into a from gone;
    with gone as (
        delete from sessions
        where expires_at < now() - interval '1 day'
           or revoked_at < now() - interval '1 day'
        returning 1
    )
    select count(*) into b from gone;
    with gone as (
        delete from jobs
        where state in ('succeeded', 'cancelled') and finished_at < now() - interval '90 days'
        returning 1
    )
    select count(*) into c from gone;
    return query select a, b, c;
end
$$;
revoke all on function vp_platform_sweep() from public;
grant execute on function vp_platform_sweep() to vp_app;
