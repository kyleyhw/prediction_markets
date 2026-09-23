-- The market list shows each strategy's latest forecast per market in a
-- domain (`WorkspaceView.latest_forecasts`); this index answers it without
-- sorting the workspace's forecasts.
create index forecasts_latest_idx
    on forecasts (workspace_id, domain, market_id, forecaster, at desc);
