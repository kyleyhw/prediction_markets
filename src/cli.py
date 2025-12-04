import argparse
import sys
from src.analysis.plot_starladder import plot_starladder_odds
from src.analysis.plot_kalshi_starladder import plot_kalshi_starladder
from src.analysis.compare_starladder import compare_starladder_odds
from src.analysis.plot_spread_candles import plot_spread_candles
from src.analysis.plot_arbitrage_history import plot_arbitrage_history

def main():
    parser = argparse.ArgumentParser(description="Prediction Markets Analysis CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    subparsers.required = True

    # 1. Plot Polymarket Odds
    p_poly = subparsers.add_parser("plot-poly", help="Plot Polymarket Starladder Odds")
    p_poly.set_defaults(func=plot_starladder_odds)

    # 2. Plot Kalshi Odds
    p_kalshi = subparsers.add_parser("plot-kalshi", help="Plot Kalshi Starladder Odds")
    p_kalshi.set_defaults(func=plot_kalshi_starladder)

    # 3. Compare Odds
    p_compare = subparsers.add_parser("compare", help="Compare Polymarket vs Kalshi Odds")
    p_compare.set_defaults(func=compare_starladder_odds)

    # 4. Spread Candles
    p_spread = subparsers.add_parser("spread", help="Visualize Bid/Ask Spread Candles")
    p_spread.set_defaults(func=plot_spread_candles)

    # 5. Arbitrage History
    p_arb = subparsers.add_parser("arbitrage", help="Plot Arbitrage History Over Time")
    p_arb.set_defaults(func=plot_arbitrage_history)

    # 6. Slippage Analysis
    from src.analysis.analyze_slippage import analyze_slippage
    p_slip = subparsers.add_parser("slippage", help="Analyze Market Slippage and Depth")
    p_slip.set_defaults(func=analyze_slippage)

    # Parse and Execute
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
