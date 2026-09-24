-- Collaboration and delivery (plan, Phase 18; docs/collaboration.md).
--
-- Teams are workspaces with more than one member. What crosses the
-- tenancy boundary does so only through the functions below, each running
-- as the table owner and each doing one narrow thing: accept an invitation
-- addressed to the signed-in person, move a session to another workspace
-- its user belongs to, list a person's workspaces, show a public share,
-- read opted-in settlements for the leaderboards, find a channel for an
-- incoming webhook, and claim and finish outgoing messages.

-- ------------------------------------------------------------------ teams

create table invitations (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    email        text not null check (position('@' in email) > 1),
    role         text not null check (role in ('editor', 'viewer')),
    token_hash   text not null unique,
    invited_by   uuid references users (id) on delete set null,
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null default now() + interval '7 days',
    accepted_at  timestamptz,
    revoked_at   timestamptz
);
create index invitations_workspace_idx on invitations (workspace_id, created_at desc);
alter table invitations enable row level security;
create policy invitations_tenant on invitations
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- Teammates see each other's address; nothing else of each other.
create policy users_team on users
    for select using (
        id in (select m.user_id from memberships m
                where m.workspace_id = vp_current_workspace())
    );

-- A team always keeps an owner: the last owner cannot leave, be removed
-- or be demoted while anyone else is still a member. A workspace nobody
-- else belongs to may lose its last membership (account deletion does
-- that before deleting the workspace, migration 0016); a last owner of a
-- team hands it over before deleting their account.
create or replace function vp_keep_an_owner() returns trigger
    language plpgsql
as $$
begin
    if old.role = 'owner'
       and (tg_op = 'DELETE' or new.role <> 'owner')
       and not exists (
           select 1 from memberships m
            where m.workspace_id = old.workspace_id and m.role = 'owner'
              and m.user_id <> old.user_id)
       and exists (
           select 1 from memberships m
            where m.workspace_id = old.workspace_id and m.user_id <> old.user_id) then
        raise exception 'a workspace must keep at least one owner';
    end if;
    return coalesce(new, old);
end
$$;
create trigger memberships_keep_owner before update or delete on memberships
    for each row execute function vp_keep_an_owner();

-- Accept an invitation for the person whose session this is: the token
-- must be live and addressed to that person's email. Moves the session to
-- the workspace joined. Returns the workspace, or nothing.
create or replace function vp_accept_invitation(p_token_hash text, p_session_hash text)
    returns uuid
    language plpgsql security definer
    set search_path = public, pg_temp
as $$
declare
    v_user uuid;
    v_email text;
    v_inv invitations%rowtype;
begin
    select s.user_id into v_user from sessions s
     where s.session_hash = p_session_hash and s.revoked_at is null
       and s.expires_at > now();
    if v_user is null then
        return null;
    end if;
    select u.email into v_email from users u where u.id = v_user;
    update invitations i set accepted_at = now()
     where i.token_hash = p_token_hash and i.accepted_at is null
       and i.revoked_at is null and i.expires_at > now()
       and lower(i.email) = lower(v_email)
    returning * into v_inv;
    if v_inv.id is null then
        return null;
    end if;
    insert into memberships (workspace_id, user_id, role)
        values (v_inv.workspace_id, v_user, v_inv.role)
        on conflict (workspace_id, user_id) do nothing;
    update sessions set workspace_id = v_inv.workspace_id
     where session_hash = p_session_hash;
    return v_inv.workspace_id;
end
$$;

-- Move a session to another workspace its user belongs to.
create or replace function vp_switch_workspace(p_session_hash text, p_workspace uuid)
    returns boolean
    language plpgsql security definer
    set search_path = public, pg_temp
as $$
begin
    update sessions s set workspace_id = p_workspace
     where s.session_hash = p_session_hash and s.revoked_at is null
       and s.expires_at > now()
       and exists (select 1 from memberships m
                    where m.user_id = s.user_id and m.workspace_id = p_workspace);
    return found;
end
$$;

-- The workspaces a session's user belongs to, with their names.
create or replace function vp_my_workspaces(p_session_hash text)
    returns table (workspace_id uuid, name text, role text, members bigint)
    language sql stable security definer
    set search_path = public, pg_temp
as $$
    select w.id, w.name, m.role,
           (select count(*) from memberships x where x.workspace_id = w.id)
      from sessions s
      join memberships m on m.user_id = s.user_id
      join workspaces w on w.id = m.workspace_id
     where s.session_hash = p_session_hash and s.revoked_at is null
       and s.expires_at > now()
     order by m.created_at
$$;

create table activity (
    id           bigint generated always as identity primary key,
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    user_id      uuid references users (id) on delete set null
                 default vp_current_user_id(),
    action       text not null,
    subject_kind text,
    subject_id   text,
    detail       jsonb not null default '{}'::jsonb,
    at           timestamptz not null default now()
);
create index activity_workspace_idx on activity (workspace_id, at desc);
alter table activity enable row level security;
create policy activity_tenant on activity
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- ---------------------------------------------------------- sharing, forks

alter table strategies add column provenance jsonb;

create table shares (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    strategy_id  uuid not null references strategies (id) on delete cascade,
    slug         text not null unique check (slug ~ '^[A-Za-z0-9_-]{16,64}$'),
    show_pnl     boolean not null default false,
    show_spec    boolean not null default false,
    show_author  boolean not null default false,
    snapshot     jsonb not null,
    views        bigint not null default 0,
    forks        bigint not null default 0,
    created_by   uuid references users (id) on delete set null,
    created_at   timestamptz not null default now(),
    refreshed_at timestamptz not null default now(),
    revoked_at   timestamptz
);
create unique index shares_live_idx on shares (strategy_id) where revoked_at is null;
alter table shares enable row level security;
create policy shares_tenant on shares
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- The public's only view of a share: its snapshot, counted.
create or replace function vp_share_view(p_slug text, p_count boolean)
    returns jsonb
    language plpgsql security definer
    set search_path = public, pg_temp
as $$
declare
    v_snapshot jsonb;
begin
    if p_count then
        update shares set views = views + 1
         where slug = p_slug and revoked_at is null
        returning snapshot into v_snapshot;
    else
        select snapshot into v_snapshot from shares
         where slug = p_slug and revoked_at is null;
    end if;
    return v_snapshot;
end
$$;

create or replace function vp_share_forked(p_slug text)
    returns void
    language sql security definer
    set search_path = public, pg_temp
as $$
    update shares set forks = forks + 1 where slug = p_slug and revoked_at is null
$$;

-- ---------------------------------------------------------------- comments

create table comments (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    subject_kind text not null check (subject_kind in ('run', 'market', 'strategy')),
    subject_id   text not null check (length(subject_id) between 1 and 200),
    parent_id    uuid references comments (id) on delete cascade,
    user_id      uuid references users (id) on delete set null
                 default vp_current_user_id(),
    body         text not null check (length(trim(body)) between 1 and 4000),
    created_at   timestamptz not null default now(),
    edited_at    timestamptz,
    deleted_at   timestamptz,
    hidden_by    uuid references users (id) on delete set null,
    hidden_at    timestamptz
);
create index comments_subject_idx on comments (workspace_id, subject_kind, subject_id, created_at);
alter table comments enable row level security;
create policy comments_tenant on comments
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- ----------------------------------------------------------- notifications

create table notifications (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    user_id      uuid not null references users (id) on delete cascade,
    kind         text not null,
    title        text not null,
    body         text not null default '',
    link         text,
    created_at   timestamptz not null default now(),
    read_at      timestamptz
);
create index notifications_user_idx on notifications (user_id, created_at desc);
alter table notifications enable row level security;
-- Anyone in the workspace may notify a member; each reads only their own.
create policy notifications_insert on notifications
    for insert with check (workspace_id = vp_current_workspace());
create policy notifications_own on notifications
    for select using (workspace_id = vp_current_workspace()
                      and user_id = vp_current_user_id());
create policy notifications_own_update on notifications
    for update using (workspace_id = vp_current_workspace()
                      and user_id = vp_current_user_id());

create table notification_prefs (
    user_id      uuid not null references users (id) on delete cascade
                 default vp_current_user_id(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    prefs        jsonb not null default '{}'::jsonb,
    updated_at   timestamptz not null default now(),
    primary key (user_id, workspace_id)
);
alter table notification_prefs enable row level security;
-- Read by teammates' actions (to route a notice), written by the person.
create policy notification_prefs_read on notification_prefs
    for select using (workspace_id = vp_current_workspace());
create policy notification_prefs_own on notification_prefs
    for insert with check (workspace_id = vp_current_workspace()
                           and user_id = vp_current_user_id());
create policy notification_prefs_own_update on notification_prefs
    for update using (workspace_id = vp_current_workspace()
                      and user_id = vp_current_user_id());

-- ------------------------------------------------------------- leaderboards

create table leaderboard_optins (
    strategy_id  uuid primary key references strategies (id) on delete cascade,
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    display_name text not null check (length(trim(display_name)) between 1 and 60),
    opted_in_by  uuid references users (id) on delete set null
                 default vp_current_user_id(),
    opted_in_at  timestamptz not null default now()
);
alter table leaderboard_optins enable row level security;
create policy leaderboard_optins_tenant on leaderboard_optins
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- The platform's own: everyone reads the boards.
create table leaderboards (
    board        text primary key,
    body         jsonb not null,
    computed_at  timestamptz not null default now()
);

-- Settlements of opted-in strategies only, with each order's domain.
create or replace function vp_leaderboard_rows()
    returns table (strategy_id uuid, display_name text, domain text,
                   at timestamptz, brier double precision,
                   brier_market double precision, pnl double precision)
    language sql stable security definer
    set search_path = public, pg_temp
as $$
    select o.strategy_id, o.display_name,
           coalesce(ord.entry -> 'data' ->> 'domain', a.domains[1]),
           s.at,
           (s.entry -> 'data' ->> 'brier')::double precision,
           (s.entry -> 'data' ->> 'brier_market')::double precision,
           (s.entry -> 'data' ->> 'pnl')::double precision
      from leaderboard_optins o
      join strategy_versions v on v.strategy_id = o.strategy_id
      join paper_accounts a on a.strategy_version_id = v.id
      join ledger_entries s on s.account_id = a.id and s.kind = 'settlement'
      left join lateral (
          select e.entry from ledger_entries e
           where e.account_id = a.id and e.kind = 'order'
             and e.entry -> 'data' ->> 'market_id' = s.entry -> 'data' ->> 'market_id'
           order by e.seq desc limit 1
      ) ord on true
     where s.entry -> 'data' ->> 'brier_market' is not null
$$;

-- ------------------------------------------------------ channels and chats

create table channels (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    kind         text not null check (kind in ('email', 'webhook', 'telegram',
                                               'slack', 'discord')),
    name         text not null check (length(trim(name)) between 1 and 100),
    target       text not null check (length(target) between 1 and 500),
    ciphertext   bytea,
    wrapped_key  bytea,
    created_by   uuid references users (id) on delete set null
                 default vp_current_user_id(),
    created_at   timestamptz not null default now(),
    disabled_at  timestamptz,
    unique (workspace_id, name)
);
alter table channels enable row level security;
create policy channels_tenant on channels
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

create table channel_senders (
    channel_id   uuid not null references channels (id) on delete cascade,
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    sender_ref   text not null,
    display      text not null default '',
    approved_by  uuid references users (id) on delete set null,
    approved_at  timestamptz not null default now(),
    primary key (channel_id, sender_ref)
);
alter table channel_senders enable row level security;
create policy channel_senders_tenant on channel_senders
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

create table pairing_codes (
    code         text primary key check (code ~ '^[A-Z0-9]{8}$'),
    channel_id   uuid not null references channels (id) on delete cascade,
    workspace_id uuid not null references workspaces (id) on delete cascade,
    sender_ref   text not null,
    display      text not null default '',
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null default now() + interval '1 hour',
    approved_at  timestamptz
);
alter table pairing_codes enable row level security;
create policy pairing_codes_tenant on pairing_codes
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

create table chat_sessions (
    channel_id      uuid not null references channels (id) on delete cascade,
    workspace_id    uuid not null references workspaces (id) on delete cascade,
    chat_ref        text not null,
    conversation_id uuid references conversations (id) on delete set null,
    updated_at      timestamptz not null default now(),
    primary key (channel_id, chat_ref)
);
alter table chat_sessions enable row level security;
create policy chat_sessions_tenant on chat_sessions
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- An incoming webhook names its channel in the URL; this is how the
-- service finds the channel's workspace and secret before any session
-- exists. The caller verifies the platform's signature with the secret
-- before acting on anything.
create or replace function vp_channel_for_hook(p_channel uuid)
    returns table (workspace_id uuid, kind text, target text, ciphertext bytea,
                   wrapped_key bytea, created_by uuid)
    language sql stable security definer
    set search_path = public, pg_temp
as $$
    select c.workspace_id, c.kind, c.target, c.ciphertext, c.wrapped_key, c.created_by
      from channels c where c.id = p_channel and c.disabled_at is null
$$;

-- ------------------------------------------------------------------ briefs

create table briefs (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    template     text not null check (template in ('disagreements', 'settlements', 'weekly')),
    variables    jsonb not null default '{}'::jsonb,
    cron         text not null,
    timezone     text not null default 'UTC',
    channel_id   uuid references channels (id) on delete set null,
    enabled      boolean not null default false,
    proposed_by  text not null check (proposed_by in ('person', 'assistant')),
    created_by   uuid references users (id) on delete set null
                 default vp_current_user_id(),
    confirmed_by uuid references users (id) on delete set null,
    confirmed_at timestamptz,
    last_body    text,
    last_run_at  timestamptz,
    created_at   timestamptz not null default now()
);
alter table briefs enable row level security;
create policy briefs_tenant on briefs
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- -------------------------------------------------------- outgoing webhooks

create table webhooks (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    url          text not null check (url ~ '^https?://'),
    events       text[] not null check (cardinality(events) >= 1),
    ciphertext   bytea not null,
    wrapped_key  bytea not null,
    created_by   uuid references users (id) on delete set null
                 default vp_current_user_id(),
    created_at   timestamptz not null default now(),
    disabled_at  timestamptz
);
alter table webhooks enable row level security;
create policy webhooks_tenant on webhooks
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- ------------------------------------------------------------------ outbox

create table outbox (
    id              uuid primary key default gen_random_uuid(),
    workspace_id    uuid not null default vp_current_workspace()
                    references workspaces (id) on delete cascade,
    channel_id      uuid references channels (id) on delete cascade,
    webhook_id      uuid references webhooks (id) on delete cascade,
    address         text,
    kind            text not null,
    payload         jsonb not null,
    state           text not null default 'queued'
                    check (state in ('queued', 'sending', 'sent', 'dead')),
    attempts        int not null default 0,
    next_attempt_at timestamptz not null default now(),
    lease_until     timestamptz,
    receipt         jsonb,
    error           text,
    created_at      timestamptz not null default now(),
    sent_at         timestamptz,
    check (num_nonnulls(channel_id, webhook_id, address) = 1)
);
create index outbox_due_idx on outbox (next_attempt_at) where state = 'queued';
create index outbox_workspace_idx on outbox (workspace_id, created_at desc);
alter table outbox enable row level security;
create policy outbox_tenant on outbox
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- Claim due messages for delivery, with what sending needs. A claim is a
-- five-minute lease; a lease that lapses is claimed again.
create or replace function vp_outbox_claim(p_limit int)
    returns table (id uuid, workspace_id uuid, kind text, payload jsonb,
                   attempts int, address text, channel_kind text, target text,
                   ciphertext bytea, wrapped_key bytea, url text)
    language plpgsql security definer
    set search_path = public, pg_temp
as $$
begin
    return query
    with due as (
        select o.id from outbox o
         where (o.state = 'queued' and o.next_attempt_at <= now())
            or (o.state = 'sending' and o.lease_until < now())
         order by o.next_attempt_at
         limit least(greatest(p_limit, 1), 500)
         for update skip locked
    ), claimed as (
        update outbox o set state = 'sending', attempts = o.attempts + 1,
               lease_until = now() + interval '5 minutes'
          from due where o.id = due.id
        returning o.*
    )
    select c.id, c.workspace_id, c.kind, c.payload, c.attempts, c.address,
           ch.kind, ch.target,
           coalesce(ch.ciphertext, w.ciphertext), coalesce(ch.wrapped_key, w.wrapped_key),
           w.url
      from claimed c
      left join channels ch on ch.id = c.channel_id
      left join webhooks w on w.id = c.webhook_id;
end
$$;

-- Record a delivery's outcome: sent with its receipt, retried later, or dead.
create or replace function vp_outbox_finish(p_id uuid, p_state text, p_receipt jsonb,
                                            p_error text, p_retry_at timestamptz)
    returns void
    language plpgsql security definer
    set search_path = public, pg_temp
as $$
begin
    if p_state not in ('sent', 'queued', 'dead') then
        raise exception 'not a delivery outcome: %', p_state;
    end if;
    update outbox set state = p_state, receipt = p_receipt, error = left(p_error, 500),
           next_attempt_at = coalesce(p_retry_at, next_attempt_at),
           sent_at = case when p_state = 'sent' then now() else sent_at end,
           lease_until = null
     where id = p_id;
end
$$;

-- ---------------------------------------------------------------- the jobs

create or replace function vp_jobs_enqueue_platform(
    p_kind text, p_payload jsonb, p_idempotency_key text, p_priority int, p_run_after timestamptz
)
    returns uuid
    language plpgsql
    security definer
    set search_path = public, pg_temp
as $$
declare
    new_id uuid;
begin
    if p_kind not in ('scheduler', 'snapshot', 'dataset', 'evidence', 'partitions',
                      'reconcile', 'sweep', 'sample_cycle', 'sample_settle',
                      'signal_bench', 'benchmark_freeze', 'benchmark_score',
                      'deliver', 'leaderboard') then
        raise exception 'not a platform job kind: %', p_kind;
    end if;
    insert into jobs (kind, payload, idempotency_key, priority, run_after)
    values (p_kind, coalesce(p_payload, '{}'::jsonb), p_idempotency_key,
            coalesce(p_priority, 100), coalesce(p_run_after, now()))
    on conflict do nothing
    returning id into new_id;
    return new_id;
end
$$;

insert into schedules (name, kind, payload, cron, timezone, next_run_at) values
    ('deliver', 'deliver', '{}', '* * * * *', 'UTC', now()),
    ('leaderboard', 'leaderboard', '{}', '20 * * * *', 'UTC', now());

revoke all on function vp_accept_invitation(text, text), vp_switch_workspace(text, uuid),
    vp_my_workspaces(text), vp_share_view(text, boolean), vp_share_forked(text),
    vp_leaderboard_rows(), vp_channel_for_hook(uuid), vp_outbox_claim(int),
    vp_outbox_finish(uuid, text, jsonb, text, timestamptz) from public;
grant execute on function vp_accept_invitation(text, text), vp_switch_workspace(text, uuid),
    vp_my_workspaces(text), vp_share_view(text, boolean), vp_share_forked(text),
    vp_leaderboard_rows(), vp_channel_for_hook(uuid), vp_outbox_claim(int),
    vp_outbox_finish(uuid, text, jsonb, text, timestamptz) to vp_app;
