# Archived: prediction_markets

This directory holds the original `prediction_markets` project unchanged. It
compared Polymarket and Kalshi prices for CS2 and English Premier League
markets, fetched price history for active markets, and analysed spreads and
slippage. Its own README is at [README_original.md](README_original.md) and its
plan is Phases 1–5 of the root [PROJECT_PLAN.md](../../PROJECT_PLAN.md).

The code is kept for reference and is not wired into the current package: the
`pm` entry point and the `src.` imports no longer resolve from the repository
root, and the archive is excluded from linting and type checking. Nothing here
is deleted; the Polymarket tag IDs and keyword filters in
`src/analysis/market_config.json` and `src/config.py` are the seed for the
current project's domain adapters.
