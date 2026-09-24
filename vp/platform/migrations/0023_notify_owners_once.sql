-- A receiver that is down during a burst killed one message after another,
-- and each death told the owners again: 44 notices in one measured outage
-- (tests/reports/phase18_collaboration.md). An owner is now told once an
-- hour per kind and title; the Delivery page counts every failure.
create or replace function vp_notify_owners(p_workspace uuid, p_kind text,
                                            p_title text, p_body text)
    returns int
    language plpgsql security definer
    set search_path = public, pg_temp
as $$
declare
    n int;
begin
    insert into notifications (workspace_id, user_id, kind, title, body)
    select m.workspace_id, m.user_id, p_kind, left(p_title, 200), left(p_body, 2000)
      from memberships m
     where m.workspace_id = p_workspace and m.role = 'owner'
       and not exists (
           select 1 from notifications n
            where n.workspace_id = p_workspace and n.user_id = m.user_id
              and n.kind = p_kind and n.title = left(p_title, 200)
              and n.created_at > now() - interval '1 hour');
    get diagnostics n = row_count;
    return n;
end
$$;
