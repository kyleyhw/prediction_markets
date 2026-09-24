-- Job claims read the index in order (Phase 21, tests/reports/
-- phase21_scale.md). With `kind = any (kinds)` the planner scanned every
-- queued job and sorted them on disk for each claim: 30 ms at 30,000
-- queued, O(n), 261 claims a second from eight claimers. The head of each
-- kind is now taken from an index in exactly the claim's order, and the
-- best head across the kinds wins: 0.1 ms at the same depth. Priority
-- across kinds is unchanged. Heads of the other kinds are locked only
-- until the claim's statement commits.
drop index jobs_claim_idx;
create index jobs_claim_idx on jobs (kind, priority, run_after, created_at)
    where state = 'queued';

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
    select h.* into picked from unnest(p_kinds) k(kind)
    cross join lateral (
        select * from jobs j
        where j.state = 'queued'
          and j.kind = k.kind
          and j.run_after <= now()
          and (j.workspace_id is null or not vp_halted(j.workspace_id))
        order by j.priority, j.run_after, j.created_at
        for update skip locked
        limit 1
    ) h
    where not exists (select 1 from ops_flags f where f.name = 'drain:' || k.kind)
    order by h.priority, h.run_after, h.created_at
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
