-- Migration 0007: the queue's gauges, and a request limit per address.
--
-- `vp_queue_stats` gives the metrics the queue's shape across every
-- workspace: counts and the oldest age by kind and state, nothing else.
--
-- `vp_rate_limit` counts requests per key in fixed windows. Sign-in asks it
-- about the client's address, so one address cannot send links to many
-- addresses (migration 0002 already limits links per email address).

create or replace function vp_queue_stats()
    returns table (kind text, state text, jobs bigint, oldest_seconds double precision)
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select j.kind, j.state, count(*),
           extract(epoch from now() - min(case when j.state = 'queued'
                                               then greatest(j.run_after, j.created_at) end))::float8
    from jobs j
    where j.state in ('queued', 'running', 'dead')
    group by 1, 2
$$;

create table request_limits (
    key          text not null,
    window_start timestamptz not null,
    hits         int not null default 0,
    primary key (key, window_start)
);
alter table request_limits enable row level security;
revoke all on table request_limits from vp_app;

create or replace function vp_rate_limit(p_key text, p_limit int, p_window_seconds int)
    returns boolean
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    start_at timestamptz;
    n int;
begin
    if p_limit < 1 or p_window_seconds < 1 or p_window_seconds > 86400 then
        raise exception 'bad limit';
    end if;
    start_at := to_timestamp(floor(extract(epoch from now()) / p_window_seconds) * p_window_seconds);
    insert into request_limits (key, window_start, hits) values (left(p_key, 200), start_at, 1)
    on conflict (key, window_start) do update set hits = request_limits.hits + 1
    returning hits into n;
    delete from request_limits where window_start < now() - interval '1 day';
    return n <= p_limit;
end
$$;

revoke all on function vp_queue_stats(), vp_rate_limit(text, int, int) from public;
grant execute on function vp_queue_stats(), vp_rate_limit(text, int, int) to vp_app;
