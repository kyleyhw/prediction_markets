-- A queued job's wait starts when it may run: one scheduled for later is
-- not waiting yet, so it no longer drags the oldest age below zero.
create or replace function vp_queue_stats()
    returns table (kind text, state text, jobs bigint, oldest_seconds double precision)
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select j.kind, j.state, count(*),
           extract(epoch from now() - min(case when j.state = 'queued'
                                                and j.run_after <= now()
                                               then greatest(j.run_after, j.created_at) end))::float8
    from jobs j
    where j.state in ('queued', 'running', 'dead')
    group by 1, 2
$$;
revoke all on function vp_queue_stats() from public;
