-- The daily evidence capture (plan, task 73; docs/evidence.md): the
-- point-in-time weather forecasts of the last three days, once a day after
-- the morning runs; the hourly `evidence` schedule runs the rest.
insert into schedules (name, kind, payload, cron, timezone, next_run_at) values
    ('evidence-daily', 'evidence', '{"sources": ["open_meteo_runs"]}',
     '30 6 * * *', 'UTC', now());
