-- Export of everything the platform holds on the signed-in person (Phase
-- 21, task 110; the privacy notice promises it). It mirrors
-- vp_delete_account: tables are found by their columns, so a table added
-- later is exported without a change here. A table with a `user_id` gives
-- the person's own rows (and the workspace's rows with no person), one with
-- only a `workspace_id` gives the workspace's rows, which every member
-- already reads. Hashes of secrets, encrypted secrets, lease tokens and
-- pairing codes are left out: they are ours to check, not the person's
-- data, and useless outside. The platform's audit log is not exported.
create or replace function vp_export_account()
    returns jsonb
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    uid uuid := vp_current_user_id();
    ws uuid := vp_current_workspace();
    t record;
    cols text;
    cond text;
    got jsonb;
    out jsonb;
begin
    if uid is null or ws is null then
        raise exception 'no signed-in person';
    end if;
    out := jsonb_build_object(
        'users', (select jsonb_agg(to_jsonb(u)) from users u where u.id = uid),
        'workspaces', (select jsonb_agg(to_jsonb(w)) from workspaces w where w.id = ws)
    );
    for t in
        select c.oid, c.relname,
               bool_or(a.attname = 'workspace_id') as has_ws,
               bool_or(a.attname = 'user_id') as has_user
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
          join pg_attribute a on a.attrelid = c.oid and not a.attisdropped
         where n.nspname = 'public' and c.relkind in ('r', 'p')
           and not c.relispartition
           and a.attname in ('workspace_id', 'user_id')
           and c.relname not in ('audit_entries', 'workspaces', 'users')
         group by c.oid, c.relname
         order by c.relname
    loop
        select string_agg(quote_ident(a.attname), ', ' order by a.attnum) into cols
          from pg_attribute a
         where a.attrelid = t.oid and a.attnum > 0 and not a.attisdropped
           and a.attname not in ('token_hash', 'session_hash', 'ciphertext',
                                 'wrapped_key', 'lease_token', 'code');
        cond := case
            when t.has_user and t.has_ws then
                'user_id = $1 or (user_id is null and workspace_id = $2)'
            when t.has_user then 'user_id = $1'
            else 'workspace_id = $2'
        end;
        execute format(
            'select coalesce(jsonb_agg(to_jsonb(r)), ''[]'') from (select %s from %I where %s) r',
            cols, t.relname, cond
        ) into got using uid, ws;
        out := out || jsonb_build_object(t.relname, got);
    end loop;
    return out;
end
$$;
revoke all on function vp_export_account() from public;
grant execute on function vp_export_account() to vp_app;
