-- Weather has far more settled markets than the other domains (about 146,000
-- in September 2026), so its daily build fetches histories only for the
-- 2,000 that ended most recently; earlier ones already held are never
-- fetched again (docs/platform.md, "Jobs").
update schedules
   set payload = '{"domain": "weather", "history": true, "history_limit": 2000}'
 where name = 'dataset-weather';
