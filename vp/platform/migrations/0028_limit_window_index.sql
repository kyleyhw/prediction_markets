-- Every rate-limit check also deletes the windows older than a day
-- (Phase 21, tests/reports/phase21_scale.md). The key leads the primary
-- key, so the delete scanned the table: at a day of windows for 1,000
-- tokens (1.4 million rows) each check took 148 ms. With this index, 1 ms.
create index request_limits_window_idx on request_limits (window_start);
