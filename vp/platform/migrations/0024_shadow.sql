-- The shadow forecaster (docs/shadow.md, Phase 19): a person links a public
-- address's record to their account and gets a report card. The import is
-- the person's own, like a conversation: teammates do not see it.
create table shadow_imports (
    id              uuid primary key default gen_random_uuid(),
    workspace_id    uuid not null default vp_current_workspace()
                    references workspaces (id) on delete cascade,
    user_id         uuid not null default vp_current_user_id()
                    references users (id) on delete cascade,
    address         text not null check (address ~ '^0x[0-9a-f]{40}$'),
    -- Linking the address is the person's act: what they agreed to, when.
    consent_version text not null,
    consented_at    timestamptz not null default now(),
    -- The one-time message a wallet signs to prove control (optional).
    nonce           text not null,
    verified_at     timestamptz,
    verified_by     text,
    state           text not null default 'queued'
                    check (state in ('queued', 'running', 'done', 'failed')),
    job_id          uuid,
    card            jsonb,
    error           text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (user_id, workspace_id, address)
);
alter table shadow_imports enable row level security;
create policy shadow_imports_own on shadow_imports
    for all using (workspace_id = vp_current_workspace()
                   and user_id = vp_current_user_id())
    with check (workspace_id = vp_current_workspace()
                and user_id = vp_current_user_id());
