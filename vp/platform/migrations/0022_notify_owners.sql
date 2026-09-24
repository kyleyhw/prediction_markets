-- Platform jobs act for nobody, so they cannot write a workspace's rows.
-- This is the one thing they may do there: tell its owners something
-- (a message that could not be delivered, a halt). It writes notification
-- rows only, for owners only, and nothing else.
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
     where m.workspace_id = p_workspace and m.role = 'owner';
    get diagnostics n = row_count;
    return n;
end
$$;
revoke all on function vp_notify_owners(uuid, text, text, text) from public;
grant execute on function vp_notify_owners(uuid, text, text, text) to vp_app;
