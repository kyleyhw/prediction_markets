-- While the platform or a workspace is halted, the workspace's schedules
-- move on without queueing: a paused account's hourly cycle is skipped, not
-- saved up to run all at once on resume. Found on the stand-in, where
-- fifteen paused workspaces queued thirty jobs an hour that no worker
-- could claim, and the backlog alert fired for them.
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
    if s.workspace_id is null or not vp_halted(s.workspace_id) then
        insert into jobs (workspace_id, created_by, kind, payload, idempotency_key, priority)
        values (s.workspace_id, s.created_by, s.kind, s.payload,
                'schedule:' || s.id || ':' || to_char(p_fired_at at time zone 'UTC',
                                                      'YYYYMMDD"T"HH24MISS'), 100)
        on conflict do nothing
        returning id into new_id;
    end if;
    update schedules set last_run_at = p_fired_at, next_run_at = p_next where id = p_id;
    return new_id;
end
$$;

-- A job waiting in a halted workspace is waiting on purpose: it is counted,
-- but it does not age the queue the backlog alert watches.
create or replace function vp_queue_stats()
    returns table (kind text, state text, jobs bigint, oldest_seconds double precision)
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select j.kind, j.state, count(*),
           extract(epoch from now() - min(case when j.state = 'queued'
                                                and j.run_after <= now()
                                                and (j.workspace_id is null
                                                     or not vp_halted(j.workspace_id))
                                               then greatest(j.run_after, j.created_at) end))::float8
    from jobs j
    where j.state in ('queued', 'running', 'dead')
    group by 1, 2
$$;
revoke all on function vp_schedules_fire(uuid, timestamptz, timestamptz), vp_queue_stats() from public;
