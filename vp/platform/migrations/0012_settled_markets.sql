-- The venue's own record of a market it has resolved, fetched once for
-- every account holding the market. Settlement asked the venue for the same
-- markets once per account, so its requests grew with the number of people
-- (plan, task 38). Shared like `resolutions`: nothing in it is a person's.
create table settled_markets (
    condition_id text primary key,
    record       jsonb not null,
    fetched_at   timestamptz not null default now()
);
