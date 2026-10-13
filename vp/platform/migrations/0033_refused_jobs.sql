-- A job can be refused: it fails at once, without the retries a transient
-- failure gets (2026-10-13). Found running the free demo: a strategy turn
-- whose person the demo may not serve was retried three times, though
-- where a person is does not change in a minute. The worker finishes such
-- a job as 'refused'; it is recorded dead with its reason.
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
    if p_state not in ('succeeded', 'failed', 'cancelled', 'refused') then
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
        state = case when p_state in ('failed', 'refused') then 'dead' else p_state end,
        result = p_result,
        error = left(p_error, 4000),
        lease_token = null,
        lease_until = null,
        finished_at = now(),
        progress = case when p_state = 'succeeded'
                        then progress || '{"fraction": 1}'::jsonb else progress end
    where id = p_id;
    return case when p_state in ('failed', 'refused') then 'dead' else p_state end;
end
$$;
