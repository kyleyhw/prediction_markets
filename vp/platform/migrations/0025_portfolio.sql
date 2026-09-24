-- Strategy health and the promotion protocol (docs/portfolio.md, Phase 20).

-- The latest health of each strategy, with its transitions and CUSUM path.
-- A decayed strategy is paused (its account opens no positions) until a
-- person resumes it.
create table strategy_health (
    strategy_id  uuid primary key references strategies (id) on delete cascade,
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    state        text not null
                 check (state in ('too_early', 'healthy', 'watch', 'decayed')),
    settled      int not null,
    cusum        numeric not null,
    report       jsonb not null,
    paused_at    timestamptz,
    resumed_at   timestamptz,
    resumed_by   uuid references users (id) on delete set null,
    updated_at   timestamptz not null default now()
);
alter table strategy_health enable row level security;
create policy strategy_health_tenant on strategy_health
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());

-- Each evaluation of the criteria for one version and target, and the
-- person's approval of a passing one. Only a live approval is binding
-- (Phase 22 reads it); paper is advisory.
create table promotion_evaluations (
    id                  uuid primary key default gen_random_uuid(),
    workspace_id        uuid not null default vp_current_workspace()
                        references workspaces (id) on delete cascade,
    strategy_version_id uuid not null references strategy_versions (id) on delete cascade,
    target              text not null check (target in ('paper', 'live')),
    criteria            jsonb not null,
    passed              boolean not null,
    evaluated_by        uuid default vp_current_user_id()
                        references users (id) on delete set null,
    evaluated_at        timestamptz not null default now(),
    approved_by         uuid references users (id) on delete set null,
    approved_at         timestamptz,
    check (approved_at is null or passed)
);
alter table promotion_evaluations enable row level security;
create policy promotion_evaluations_tenant on promotion_evaluations
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());
