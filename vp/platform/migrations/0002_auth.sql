-- Migration 0002: sign-in, sessions and API tokens.
--
-- Signing in has to create a user, a workspace and a membership before any
-- workspace context exists, which the row-level security of migration 0001
-- would refuse. Rather than give the web process the owner's credentials,
-- the bootstrap happens inside the functions below, which run as their
-- owner (SECURITY DEFINER) and are the only code that crosses the tenancy
-- boundary. The web process connects as `vp_app` and can do exactly what
-- these functions allow and nothing more:
--
--   * vp_auth_request_sign_in  record a sign-in token for an address
--   * vp_auth_sign_in          exchange an unused, unexpired token for a
--                              session, creating the user on first use
--   * vp_auth_resolve_session  who a session cookie belongs to
--   * vp_auth_end_session      revoke a session
--   * vp_auth_resolve_token    who an API token belongs to
--
-- In particular there is no function that creates a session for a named
-- user: the only way to obtain one is to present a sign-in token that was
-- sent to that user's address. Every limit (token lifetime, session
-- lifetime, the sign-in rate) is fixed here rather than passed in, so a
-- caller cannot widen it.
--
-- Only hashes are stored. The token in the email, the session cookie and
-- the API token are 256-bit random values; the database holds their
-- SHA-256, so a copy of the tables grants nothing.
--
-- Every function sets its own search_path, so a caller's schema cannot
-- redirect a name inside it, and contains no dynamic SQL.

create table sign_in_tokens (
    token_hash text primary key,
    email      text not null,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    used_at    timestamptz
);

create index sign_in_tokens_email_idx on sign_in_tokens (lower(email), created_at);

create table sessions (
    session_hash text primary key,
    user_id      uuid not null references users (id) on delete cascade,
    workspace_id uuid not null references workspaces (id) on delete cascade,
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null,
    revoked_at   timestamptz
);

create index sessions_user_idx on sessions (user_id);

create table api_tokens (
    id           uuid primary key default gen_random_uuid(),
    token_hash   text not null unique,
    user_id      uuid not null references users (id) on delete cascade,
    workspace_id uuid not null references workspaces (id) on delete cascade,
    name         text not null check (length(trim(name)) between 1 and 100),
    scope        text not null check (scope in ('read', 'write')),
    created_at   timestamptz not null default now(),
    revoked_at   timestamptz
);

create index api_tokens_owner_idx on api_tokens (workspace_id, user_id);

-- Sign-in tokens and sessions are reached only through the functions.
-- Row-level security with no policy denies everything, and the privileges
-- the default grant of migration 0001 gave the application are taken back.
alter table sign_in_tokens enable row level security;
alter table sessions       enable row level security;
revoke all on table sign_in_tokens, sessions from vp_app;

-- A person manages their own tokens in the workspace they are acting in.
alter table api_tokens enable row level security;
create policy api_tokens_own on api_tokens
    for all using (
        workspace_id = vp_current_workspace() and user_id = vp_current_user_id()
    )
    with check (
        workspace_id = vp_current_workspace() and user_id = vp_current_user_id()
    );

-- At most five links per address per fifteen minutes, each good for
-- fifteen minutes. Returns false, and records nothing, over the limit; the
-- caller answers the same way either way, so the response says nothing
-- about whether the address has an account.
create function vp_auth_request_sign_in(p_email text, p_token_hash text)
    returns boolean
    language plpgsql security definer
    set search_path = public, pg_temp
as $$
begin
    if position('@' in coalesce(p_email, '')) <= 1 then
        return false;
    end if;
    if (select count(*) from sign_in_tokens
          where lower(email) = lower(p_email)
            and created_at > now() - interval '15 minutes') >= 5 then
        return false;
    end if;
    insert into sign_in_tokens (token_hash, email, expires_at)
        values (p_token_hash, p_email, now() + interval '15 minutes');
    return true;
end
$$;

-- Consume a sign-in token and open a thirty-day session. The token is
-- marked used in the same statement that checks it, so two simultaneous
-- presentations cannot both succeed. A first sign-in creates the user
-- with a personal workspace they own. Returns no row when the token is
-- unknown, used or expired.
create function vp_auth_sign_in(p_token_hash text, p_session_hash text)
    returns table (user_id uuid, workspace_id uuid)
    language plpgsql security definer
    set search_path = public, pg_temp
as $$
#variable_conflict use_column
declare
    v_email text;
    v_user  uuid;
    v_ws    uuid;
begin
    update sign_in_tokens t
       set used_at = now()
     where t.token_hash = p_token_hash
       and t.used_at is null
       and t.expires_at > now()
    returning t.email into v_email;
    if v_email is null then
        return;
    end if;

    insert into users (email) values (lower(v_email))
        on conflict (lower(email)) do nothing;
    select u.id into v_user from users u where lower(u.email) = lower(v_email);

    select m.workspace_id into v_ws
      from memberships m
     where m.user_id = v_user
     order by m.created_at
     limit 1;
    if v_ws is null then
        insert into workspaces (name) values ('Personal') returning id into v_ws;
        insert into memberships (workspace_id, user_id, role)
            values (v_ws, v_user, 'owner');
    end if;

    insert into sessions (session_hash, user_id, workspace_id, expires_at)
        values (p_session_hash, v_user, v_ws, now() + interval '30 days');
    return query select v_user, v_ws;
end
$$;

-- A live session whose user still belongs to its workspace. Removing a
-- membership therefore ends every session in that workspace at once.
create function vp_auth_resolve_session(p_session_hash text)
    returns table (user_id uuid, workspace_id uuid, role text)
    language sql stable security definer
    set search_path = public, pg_temp
as $$
    select s.user_id, s.workspace_id, m.role
      from sessions s
      join memberships m
        on m.user_id = s.user_id and m.workspace_id = s.workspace_id
     where s.session_hash = p_session_hash
       and s.revoked_at is null
       and s.expires_at > now()
$$;

create function vp_auth_end_session(p_session_hash text)
    returns void
    language sql security definer
    set search_path = public, pg_temp
as $$
    update sessions set revoked_at = now()
     where session_hash = p_session_hash and revoked_at is null
$$;

-- A live API token whose user still belongs to its workspace.
create function vp_auth_resolve_token(p_token_hash text)
    returns table (user_id uuid, workspace_id uuid, role text, scope text)
    language sql stable security definer
    set search_path = public, pg_temp
as $$
    select t.user_id, t.workspace_id, m.role, t.scope
      from api_tokens t
      join memberships m
        on m.user_id = t.user_id and m.workspace_id = t.workspace_id
     where t.token_hash = p_token_hash
       and t.revoked_at is null
$$;

-- Functions are executable by everyone unless revoked.
revoke all on function vp_auth_request_sign_in(text, text) from public;
revoke all on function vp_auth_sign_in(text, text) from public;
revoke all on function vp_auth_resolve_session(text) from public;
revoke all on function vp_auth_end_session(text) from public;
revoke all on function vp_auth_resolve_token(text) from public;

grant execute on function vp_auth_request_sign_in(text, text) to vp_app;
grant execute on function vp_auth_sign_in(text, text) to vp_app;
grant execute on function vp_auth_resolve_session(text) to vp_app;
grant execute on function vp_auth_end_session(text) to vp_app;
grant execute on function vp_auth_resolve_token(text) to vp_app;
