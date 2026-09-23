-- Strategies from conversation (plan, Phase 15; docs/strategies.md).
--
-- A strategy is a name and a lifecycle status; what it does is its
-- versions, each a spec (JSON), the spec's hash and the plain-language
-- rendering the person confirmed. A confirmed version is never edited: a
-- refinement is a new version (tasks 50, 58, 61). A strategy in paper has
-- its own paper account per version, so its P&L is its own. Conversations
-- keep the turns the compiler and the research assistant saw; per-person
-- memory is the person's own, visible and deletable (task 55); a workspace
-- may keep its own copy of a domain pack (task 56). Every table carries a
-- workspace or a person column, so account deletion (0016) reaches it.

create table strategies (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    name         text not null check (length(trim(name)) between 1 and 100),
    status       text not null default 'draft'
                 check (status in ('draft', 'previewed', 'backtested', 'paper',
                                   'retired')),
    created_by   uuid references users (id) on delete set null,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index strategies_workspace_idx on strategies (workspace_id, updated_at desc);

create table strategy_versions (
    id           uuid primary key default gen_random_uuid(),
    strategy_id  uuid not null references strategies (id) on delete cascade,
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    version      int not null check (version >= 1),
    spec         jsonb not null check (jsonb_typeof(spec) = 'object'),
    spec_hash    text not null check (spec_hash ~ '^[0-9a-f]{64}$'),
    rendering    text[] not null,
    created_by   uuid references users (id) on delete set null,
    created_at   timestamptz not null default now(),
    unique (strategy_id, version)
);

-- A version is what was confirmed; changing it would change what a run
-- card's hash points at.
create or replace function vp_versions_immutable() returns trigger
    language plpgsql
as $$
begin
    if new.spec is distinct from old.spec
       or new.spec_hash is distinct from old.spec_hash
       or new.rendering is distinct from old.rendering
       or new.version is distinct from old.version
       or new.strategy_id is distinct from old.strategy_id then
        raise exception 'a strategy version is never edited; make a new one';
    end if;
    return new;
end
$$;
create trigger strategy_versions_immutable before update on strategy_versions
    for each row execute function vp_versions_immutable();

alter table paper_accounts
    add column strategy_version_id uuid
        references strategy_versions (id) on delete set null;
alter table runs
    add column strategy_version_id uuid
        references strategy_versions (id) on delete set null,
    add column manifest jsonb,
    add column manifest_hash text;

create table conversations (
    id           uuid primary key default gen_random_uuid(),
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    user_id      uuid not null default vp_current_user_id()
                 references users (id) on delete cascade,
    strategy_id  uuid references strategies (id) on delete set null,
    cost_usd     numeric not null default 0,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create table conversation_turns (
    id              bigint generated always as identity primary key,
    conversation_id uuid not null references conversations (id) on delete cascade,
    workspace_id    uuid not null default vp_current_workspace()
                    references workspaces (id) on delete cascade,
    role            text not null check (role in ('user', 'assistant')),
    content         jsonb not null,
    created_at      timestamptz not null default now()
);
create index conversation_turns_idx on conversation_turns (conversation_id, id);

create table user_memory (
    id         uuid primary key default gen_random_uuid(),
    user_id    uuid not null default vp_current_user_id()
               references users (id) on delete cascade,
    note       text not null check (length(trim(note)) between 1 and 300),
    created_at timestamptz not null default now()
);

create table domain_packs (
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    domain       text not null,
    body         text not null check (length(body) <= 60000),
    sha256       text not null,
    updated_by   uuid references users (id) on delete set null,
    updated_at   timestamptz not null default now(),
    primary key (workspace_id, domain)
);

alter table strategies enable row level security;
create policy strategies_tenant on strategies
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

alter table strategy_versions enable row level security;
create policy strategy_versions_tenant on strategy_versions
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- A conversation is its author's, inside their workspace.
alter table conversations enable row level security;
create policy conversations_own on conversations
    for all using (workspace_id = vp_current_workspace()
                   and user_id = vp_current_user_id())
    with check (workspace_id = vp_current_workspace()
                and user_id = vp_current_user_id());

alter table conversation_turns enable row level security;
create policy conversation_turns_own on conversation_turns
    for all using (conversation_id in (select id from conversations))
    with check (workspace_id = vp_current_workspace()
                and conversation_id in (select id from conversations));

alter table user_memory enable row level security;
create policy user_memory_self on user_memory
    for all using (user_id = vp_current_user_id())
    with check (user_id = vp_current_user_id());

alter table domain_packs enable row level security;
create policy domain_packs_tenant on domain_packs
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

grant usage on all sequences in schema public to vp_app;
