-- One sample account for everyone (plan, flag F17, accepted 2026-09-23).
--
-- Every person's own sample account held the same orders on the same
-- capture, about 40,000 ledger rows a person a day. The sample strategies
-- now trade once, in a workspace of their own run by the platform, and every
-- workspace reads that account.
--
-- The platform acts in the sample workspace as a system user whose address
-- is in the reserved `.invalid` domain, to which no link can be delivered
-- and which sign-in refuses. Nothing widens the tenancy policies: a
-- workspace reads the sample only through `vp_sample_entries` and
-- `vp_sample_account`, so no existing query sees rows it did not see
-- before.

insert into users (id, email)
values ('00000000-0000-0000-0000-00000000a001', 'platform@vibe-predict.invalid')
on conflict do nothing;

insert into workspaces (id, name)
values ('00000000-0000-0000-0000-00000000a002', 'Sample strategies')
on conflict do nothing;

insert into memberships (workspace_id, user_id, role)
values ('00000000-0000-0000-0000-00000000a002',
        '00000000-0000-0000-0000-00000000a001', 'owner')
on conflict do nothing;

create or replace function vp_sample_account()
    returns table (id uuid, name text, domains text[], forecasters text[],
                   initial_cash numeric, created_at timestamptz, head_seq bigint)
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select a.id, a.name, a.domains, a.forecasters, a.initial_cash, a.created_at,
           coalesce(h.seq, -1)
    from paper_accounts a
    left join ledger_heads h on h.account_id = a.id
    where a.workspace_id = '00000000-0000-0000-0000-00000000a002'
    order by a.created_at
    limit 1
$$;

create or replace function vp_sample_entries()
    returns setof jsonb
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select e.entry from ledger_entries e
    where e.workspace_id = '00000000-0000-0000-0000-00000000a002'
      and e.account_id = (select id from vp_sample_account())
    order by e.seq
$$;

revoke all on function vp_sample_account(), vp_sample_entries() from public;
grant execute on function vp_sample_account(), vp_sample_entries() to vp_app;

insert into schedules (name, kind, payload, cron, timezone, next_run_at) values
    ('sample-cycle', 'sample_cycle', '{}', '7 * * * *', 'UTC', now()),
    ('sample-settle', 'sample_settle', '{}', '37 * * * *', 'UTC', now());
