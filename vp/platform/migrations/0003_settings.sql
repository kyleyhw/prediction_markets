-- Migration 0003: a person's interface settings.
--
-- Reading level, theme, language, interests, the sample strategy followed
-- on the home screen and progress through the guided start. They belong to
-- the person, not the workspace, so they follow them between workspaces and
-- devices; nothing in them is a secret or changes what anyone may do. The
-- shape is validated by the web service (`SettingsBody` in `web.py`); the
-- table holds one JSON document per person so a new setting needs no
-- migration.

create table user_settings (
    user_id    uuid primary key references users (id) on delete cascade,
    settings   jsonb not null default '{}'::jsonb
               check (jsonb_typeof(settings) = 'object'),
    updated_at timestamptz not null default now()
);

alter table user_settings enable row level security;

-- One's own row only, in any workspace.
create policy user_settings_self on user_settings
    for all using (user_id = vp_current_user_id())
    with check (user_id = vp_current_user_id());
