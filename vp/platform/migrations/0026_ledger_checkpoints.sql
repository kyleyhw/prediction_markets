-- Verified checkpoints of paper ledgers (Phase 21, tests/reports/
-- phase21_scale.md). A trading cycle verified and replayed an account's
-- whole chain: 1.1 s at a year's 36,500 entries, which at 30,000 accounts
-- an hour is nine cores and growing. A checkpoint holds the hash of a
-- verified entry and the replayed accounts there; a cycle verifies and
-- replays only what follows it. It advances only inside verification, and
-- a daily job still verifies every chain from its first entry.
create table ledger_checkpoints (
    account_id   uuid primary key references paper_accounts (id) on delete cascade,
    workspace_id uuid not null default vp_current_workspace()
                 references workspaces (id) on delete cascade,
    seq          bigint not null,
    hash         text not null,
    state        jsonb not null,
    at           timestamptz not null default now()
);
alter table ledger_checkpoints enable row level security;
create policy ledger_checkpoints_tenant on ledger_checkpoints
    for all using (workspace_id = vp_current_workspace())
    with check (workspace_id = vp_current_workspace());
