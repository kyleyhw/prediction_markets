-- Migration 0001: workspaces, users, memberships, and the tenancy boundary.
--
-- Everything a person owns belongs to a workspace, every tenant table
-- carries `workspace_id`, and row-level security answers every query
-- against the workspace set on the connection. A query that forgets its
-- filter therefore returns nothing rather than someone else's data.
--
-- Two roles, because the guarantee depends on it. The role that runs this
-- migration owns the tables and, as the owner, is not subject to the
-- policies: it is the bootstrap path, used only to create a user, a
-- workspace and a membership at sign-up. Everything else connects as
-- `vp_app`, which owns nothing and is subject to every policy. The
-- application must never connect as the owner, and must never connect as a
-- superuser, which bypasses row-level security unconditionally.

-- The workspace context, read from the connection rather than passed in.
-- `current_setting(..., true)` yields NULL when unset, and a comparison
-- against NULL is never true, so an unset context sees nothing.
create or replace function vp_current_workspace() returns uuid
    language sql stable
    as $$ select nullif(current_setting('vp.workspace_id', true), '')::uuid $$;

create or replace function vp_current_user_id() returns uuid
    language sql stable
    as $$ select nullif(current_setting('vp.user_id', true), '')::uuid $$;

create table workspaces (
    id          uuid primary key default gen_random_uuid(),
    name        text not null check (length(trim(name)) > 0),
    created_at  timestamptz not null default now()
);

create table users (
    id          uuid primary key default gen_random_uuid(),
    email       text not null check (position('@' in email) > 1),
    created_at  timestamptz not null default now()
);

-- Addresses differing only by case are one person.
create unique index users_email_key on users (lower(email));

create table memberships (
    workspace_id uuid not null references workspaces (id) on delete cascade,
    user_id      uuid not null references users (id) on delete cascade,
    role         text not null check (role in ('owner', 'editor', 'viewer')),
    created_at   timestamptz not null default now(),
    primary key (workspace_id, user_id)
);

create index memberships_user_idx on memberships (user_id);

alter table workspaces  enable row level security;
alter table users       enable row level security;
alter table memberships enable row level security;

create policy workspaces_tenant on workspaces
    for all using (id = vp_current_workspace())
    with check (id = vp_current_workspace());

-- Self only. A team seeing its members' details is Phase 18; closed is the
-- right direction to be wrong in.
create policy users_self on users
    for all using (id = vp_current_user_id())
    with check (id = vp_current_user_id());

-- Either the rows of the workspace being acted in, or one's own rows, so
-- that a signed-in person can list the workspaces they belong to before
-- choosing one.
create policy memberships_tenant on memberships
    for all using (
        workspace_id = vp_current_workspace()
        or user_id = vp_current_user_id()
    )
    with check (workspace_id = vp_current_workspace());

-- The application role. Created here so a fresh database is complete, but
-- it is infrastructure rather than schema: on a managed host the operator
-- may have created it already, and this is a no-op then. It is given no
-- password; the operator sets one out of band.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'vp_app') then
        create role vp_app login;
    end if;
exception
    when insufficient_privilege then
        raise exception
            'role vp_app is missing and this connection may not create it; '
            'create it first: CREATE ROLE vp_app LOGIN PASSWORD ...';
end
$$;

grant usage on schema public to vp_app;
grant select, insert, update, delete on all tables in schema public to vp_app;
alter default privileges in schema public
    grant select, insert, update, delete on tables to vp_app;

-- The migration ledger is the platform's own bookkeeping; the application
-- has no business reading or writing it. It exists before this migration
-- runs, so the blanket grant above reached it.
revoke all on table schema_migrations from vp_app;
