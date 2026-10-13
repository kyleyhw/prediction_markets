-- The sample strategies' forecasts, readable by every workspace, as their
-- ledger already is (migration 0014). Found by a simulated user on
-- 2026-10-13: a market page said "No sample strategy has forecast this
-- market yet" while the sample strategy held a position in it, because the
-- page read only the workspace's own forecasts. One market or one domain;
-- each strategy's latest forecast.
create or replace function vp_sample_forecasts(p_domain text, p_market text)
    returns table (market_id text, forecaster text, p_hat double precision,
                   cutoff timestamptz)
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select distinct on (f.market_id, f.forecaster)
           f.market_id, f.forecaster, f.p_hat, f.cutoff
      from forecasts f
     where f.workspace_id = '00000000-0000-0000-0000-00000000a002'
       and (p_domain is null or f.domain = p_domain)
       and (p_market is null or f.market_id = p_market)
     order by f.market_id, f.forecaster, f.at desc
$$;
revoke all on function vp_sample_forecasts(text, text) from public;
grant execute on function vp_sample_forecasts(text, text) to vp_app;
