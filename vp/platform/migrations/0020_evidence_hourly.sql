-- The point-in-time weather forecasts move to the hourly `evidence`
-- schedule (docs/evidence.md): the archive makes a backfilled row visible
-- an hour after its bound, the cadence a forward run can count on, so a
-- daily capture would leave forward runs without what backtests assume.
delete from schedules where name = 'evidence-daily';
