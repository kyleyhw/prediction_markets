# Day 2: How a Forecast Is Scored

**You will:** know what "better than the market" means and why it is
hard.

1. A forecast is a chance, not a yes or a no, so it is scored by how close
   the chance was to what happened. The app uses the **Brier score**: the
   square of the gap between the forecast and the outcome (1 for yes, 0
   for no), averaged over many markets. Saying 90% on something that
   happened costs 0.01; saying 90% on something that did not costs 0.81.
   Lower is better.
2. The market's own price is a forecast too, and it has a score. The app
   always compares a strategy with it. **Skill** is how much lower the
   strategy's score is than the market's, as a share: +0.05 means 5%
   better, and a negative number means worse.
3. The platform's own simple strategies do not beat the market in any area
   it covers (the [Phase 9 report](../../tests/reports/phase9_backtest.md)).
   That is the bar, and it is a high one: prices already include what
   thousands of people know.
4. In Settings, switch to **Detailed** for a moment. Every term with a
   dotted underline explains itself when you select it; the explanations
   come from one [glossary](../../vp/ui/static/app/locales/en.json).

**Try:** in Learn, open "Why is beating the market hard?" and read the
Detailed version.
