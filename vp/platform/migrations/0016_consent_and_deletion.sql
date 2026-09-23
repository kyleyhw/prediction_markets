-- Terms, age and deletion (plan, task 48).
--
-- A person confirms they are 18 or older and accepts the terms of use and
-- the privacy notice before their first session; the version they accepted
-- is kept, so a change of terms asks again. A person may delete their
-- account: their workspace, if they are its only member, goes with every
-- row it holds, then their own rows and their user. The operator's audit
-- chain and halts keep only the workspace's random id.

alter table users
    add column terms_version     text,
    add column terms_accepted_at timestamptz,
    add column adult_confirmed_at timestamptz;

-- The signed-in person accepts a version of the terms and confirms their age.
create or replace function vp_accept_terms(p_version text)
    returns void
    language sql
    security definer
    set search_path = public, pg_temp
as $$
    update users
       set terms_version = p_version, terms_accepted_at = now(),
           adult_confirmed_at = coalesce(adult_confirmed_at, now())
     where id = vp_current_user_id()
$$;

-- What the signed-in person has accepted.
create or replace function vp_consent()
    returns table (terms_version text, terms_accepted_at timestamptz,
                   adult_confirmed_at timestamptz)
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select u.terms_version, u.terms_accepted_at, u.adult_confirmed_at
    from users u where u.id = vp_current_user_id()
$$;

-- Delete the signed-in person. Returns the workspace deleted with them, or
-- null when they shared it with others (then only their membership goes).
-- Tables are found by their columns, so a table added later is not missed:
-- every table with a `workspace_id` loses the workspace's rows, every table
-- with a `user_id` loses the person's, and a leftover reference makes the
-- final delete fail rather than leave a person half-deleted.
create or replace function vp_delete_account()
    returns uuid
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    uid uuid := vp_current_user_id();
    ws uuid := vp_current_workspace();
    others int;
    t record;
begin
    if uid is null or ws is null then
        raise exception 'no signed-in person';
    end if;
    if uid = '00000000-0000-0000-0000-00000000a001' then
        raise exception 'the platform user cannot be deleted';
    end if;
    select count(*) into others from memberships m
     where m.workspace_id = ws and m.user_id <> uid;
    for t in
        select c.relname, a.attname from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
          join pg_attribute a on a.attrelid = c.oid and not a.attisdropped
         where n.nspname = 'public' and c.relkind in ('r', 'p')
           and not c.relispartition
           and a.attname in ('workspace_id', 'user_id')
           and c.relname not in ('audit_entries', 'workspaces', 'users')
    loop
        if t.attname = 'user_id' then
            execute format('delete from %I where user_id = $1', t.relname) using uid;
        elsif others = 0 then
            execute format('delete from %I where workspace_id = $1', t.relname) using ws;
        end if;
    end loop;
    for t in
        select c.relname from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
          join pg_attribute a on a.attrelid = c.oid and not a.attisdropped
         where n.nspname = 'public' and c.relkind in ('r', 'p')
           and not c.relispartition and a.attname = 'created_by'
    loop
        execute format('update %I set created_by = null where created_by = $1',
                       t.relname) using uid;
    end loop;
    delete from sign_in_tokens
     where email = (select email from users where id = uid);
    if others = 0 then
        delete from workspaces where id = ws;
    end if;
    delete from users where id = uid;
    return case when others = 0 then ws end;
end
$$;

revoke all on function vp_accept_terms(text), vp_consent(), vp_delete_account()
    from public;
grant execute on function vp_accept_terms(text), vp_consent(), vp_delete_account()
    to vp_app;
