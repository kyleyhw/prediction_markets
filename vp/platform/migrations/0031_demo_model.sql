-- The demo model and the own-key model choice (docs/models.md,
-- 2026-10-13). Without an own key the platform pays for its demo model,
-- and a daily cap across every workspace stops many accounts from each
-- spending their monthly budget on the owner's bill. A workspace's session
-- sees only its own spend (row-level security), so the day's platform-wide
-- total comes from this function, which returns one number and nothing
-- about any workspace. An own key may name the model it runs; null leaves
-- it to the strategy's tier.
alter table provider_keys add column model text;

create index spend_platform_at_idx on spend (at) where paid_by = 'platform';

create or replace function vp_platform_spend_since(p_since timestamptz)
    returns numeric
    language sql
    stable
    security definer
    set search_path = public, pg_temp
as $$
    select coalesce(sum(usd), 0) from spend
     where paid_by = 'platform' and at >= p_since
$$;
revoke all on function vp_platform_spend_since(timestamptz) from public;
grant execute on function vp_platform_spend_since(timestamptz) to vp_app;
