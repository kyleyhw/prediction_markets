-- Any model, and the free demo's daily allowance (docs/models.md,
-- 2026-10-13).
--
-- A workspace's own model may be from any provider, so the provider is no
-- longer fixed, and an OpenAI-compatible connection may carry an address.
-- A workspace keeps one own model (the code replaces any other).
alter table provider_keys drop constraint if exists provider_keys_provider_check;
alter table provider_keys add column base_url text;

-- Calls to the free demo model, per workspace per day (UTC). The platform
-- stays inside the provider's free quota by counting every call before it
-- is made; the count is the only thing kept, never the call.
create table demo_calls (
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    day          date not null default (now() at time zone 'utc')::date,
    calls        int not null default 0 check (calls >= 0),
    primary key (workspace_id, day)
);
create index demo_calls_day_idx on demo_calls (day);
alter table demo_calls enable row level security;
create policy demo_calls_tenant on demo_calls
    using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());
-- The count changes only through vp_demo_take, never by a direct write.
revoke insert, update, delete on demo_calls from vp_app;

-- Calls left today for the current workspace: the smaller of what its own
-- allowance and the platform's leave. The platform-wide total crosses
-- workspaces, which row-level security would hide, so it is computed here
-- and only the number leaves.
create or replace function vp_demo_left(p_workspace_limit int, p_platform_limit int)
    returns int
    language sql
    stable
    security definer
    set search_path = public, pg_temp
as $$
    select greatest(least(
        p_workspace_limit - coalesce((select calls from demo_calls
            where workspace_id = vp_current_workspace()
              and day = (now() at time zone 'utc')::date), 0),
        p_platform_limit - coalesce((select sum(calls) from demo_calls
            where day = (now() at time zone 'utc')::date), 0)
    ), 0)::int
$$;

-- Take one call, or refuse when either allowance is used up. One lock for
-- the whole platform, so two calls cannot both take the last one.
create or replace function vp_demo_take(p_workspace_limit int, p_platform_limit int)
    returns boolean
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
begin
    if vp_current_workspace() is null then
        raise exception 'no workspace';
    end if;
    perform pg_advisory_xact_lock(hashtextextended('demo-calls', 0));
    if vp_demo_left(p_workspace_limit, p_platform_limit) < 1 then
        return false;
    end if;
    insert into demo_calls (workspace_id, day, calls)
    values (vp_current_workspace(), (now() at time zone 'utc')::date, 1)
    on conflict (workspace_id, day) do update set calls = demo_calls.calls + 1;
    return true;
end
$$;
revoke all on function vp_demo_left(int, int) from public;
revoke all on function vp_demo_take(int, int) from public;
grant execute on function vp_demo_left(int, int) to vp_app;
grant execute on function vp_demo_take(int, int) to vp_app;
