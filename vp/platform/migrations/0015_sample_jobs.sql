-- The sample account's cycle and settlement are the platform's own jobs.
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
                      'reconcile', 'sweep', 'sample_cycle', 'sample_settle') then
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
