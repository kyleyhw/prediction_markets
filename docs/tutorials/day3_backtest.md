# Day 3: Run a Backtest

**You will:** test a strategy on markets that have already settled, and
read what it says.

1. Open **Backtests**. The form asks which markets and which strategies.
   Start with one area and the two sample strategies offered.
2. Before anything runs, the page says how many markets the test covers
   and, if a strategy uses the AI model, what it will cost from the
   month's budget. The sample strategies cost nothing.
3. Start it. The jobs panel shows its progress, and the finished run opens
   by itself.
4. In Simple the result is a few sentences, for example: "would have
   turned $1,000 into $427 over 167 bets; worse than doing nothing; its
   forecasts were less accurate than the market's own prices." **Doing
   nothing** (keeping the $1,000) is drawn dashed on every chart, because
   a strategy that just agrees with the market never bets.
5. Each forecast only saw what was known a day before the market settled.
   That rule, the **cutoff**, is what makes the test honest: without it a
   strategy could peek at the answer.

**What a backtest is not:** a promise. A strategy that did well on the
past can do badly next week, which is why paper trading comes next.

More: Learn → "What is a backtest?"
