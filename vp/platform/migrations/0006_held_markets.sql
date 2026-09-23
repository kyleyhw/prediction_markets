-- Migration 0006: which markets someone holds, for the market-data service.
--
-- The service quotes every tracked market once a minute, and a market any
-- paper account holds on every change of its best prices, so settlement
-- and the positions page read fresh prices where they matter. Knowing
-- which markets those are needs every workspace's ledger, which the
-- service may not read; this function returns the market ids and nothing
-- else: not who holds them, how many, or on which side.

create or replace function vp_held_markets()
    returns table (market_id text)
    language sql stable
    security definer
    set search_path = public, pg_temp
as $$
    select distinct o.entry -> 'data' ->> 'market_id'
    from ledger_entries o
    where o.kind = 'order'
      and o.at > now() - interval '180 days'
      and not exists (
          select 1 from ledger_entries s
          where s.account_id = o.account_id
            and s.kind = 'settlement'
            and s.entry -> 'data' ->> 'market_id' = o.entry -> 'data' ->> 'market_id'
            and s.seq > o.seq
      )
$$;
revoke all on function vp_held_markets() from public;
grant execute on function vp_held_markets() to vp_app;
