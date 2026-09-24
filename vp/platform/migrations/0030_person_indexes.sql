-- Every column that deleting or exporting a person filters on is indexed
-- (Phase 21, tests/reports/phase21_scale.md). vp_delete_account and
-- vp_export_account find their tables by the columns `workspace_id`,
-- `user_id` and `created_by`; where no index led with the column, each
-- deletion scanned the table: every paper ledger on the platform (a
-- million rows at 10,000 people, a hundred million more a day at a
-- million) and the whole job history. tests/test_platform_db.py keeps a
-- new table from missing one.
create index activity_user_id_idx on activity (user_id);
create index api_tokens_user_id_idx on api_tokens (user_id);
create index briefs_created_by_idx on briefs (created_by);
create index briefs_workspace_id_idx on briefs (workspace_id);
create index channel_senders_workspace_id_idx on channel_senders (workspace_id);
create index channels_created_by_idx on channels (created_by);
create index chat_sessions_workspace_id_idx on chat_sessions (workspace_id);
create index comments_user_id_idx on comments (user_id);
create index conversation_turns_workspace_id_idx on conversation_turns (workspace_id);
create index conversations_user_id_idx on conversations (user_id);
create index conversations_workspace_id_idx on conversations (workspace_id);
create index halts_workspace_id_idx on halts (workspace_id);
create index jobs_created_by_idx on jobs (created_by);
create index leaderboard_optins_workspace_id_idx on leaderboard_optins (workspace_id);
create index ledger_checkpoints_workspace_id_idx on ledger_checkpoints (workspace_id);
create index ledger_entries_workspace_id_idx on ledger_entries (workspace_id);
create index ledger_heads_workspace_id_idx on ledger_heads (workspace_id);
create index notification_prefs_workspace_id_idx on notification_prefs (workspace_id);
create index notifications_workspace_id_idx on notifications (workspace_id);
create index pairing_codes_workspace_id_idx on pairing_codes (workspace_id);
create index paper_accounts_created_by_idx on paper_accounts (created_by);
create index promotion_evaluations_workspace_id_idx on promotion_evaluations (workspace_id);
create index provider_keys_created_by_idx on provider_keys (created_by);
create index runs_created_by_idx on runs (created_by);
create index schedules_created_by_idx on schedules (created_by);
create index schedules_workspace_id_idx on schedules (workspace_id);
create index sessions_workspace_id_idx on sessions (workspace_id);
create index shadow_imports_workspace_id_idx on shadow_imports (workspace_id);
create index shares_created_by_idx on shares (created_by);
create index shares_workspace_id_idx on shares (workspace_id);
create index strategies_created_by_idx on strategies (created_by);
create index strategy_health_workspace_id_idx on strategy_health (workspace_id);
create index strategy_versions_created_by_idx on strategy_versions (created_by);
create index strategy_versions_workspace_id_idx on strategy_versions (workspace_id);
create index user_memory_user_id_idx on user_memory (user_id);
create index webhooks_created_by_idx on webhooks (created_by);
create index webhooks_workspace_id_idx on webhooks (workspace_id);
