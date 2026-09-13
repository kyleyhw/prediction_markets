# Scoring and Calibration

Phase 9 scores forecasts. This page gives the definitions and derivations
behind `vp.backtest.scoring`; the module docstring carries the same formulas
next to the code.

## Proper Scores

A forecast $\hat p$ of a binary event with outcome $y \in \{0, 1\}$ is scored
with

$$\text{Brier}(\hat p, y) = (\hat p - y)^2, \qquad
\text{Log}(\hat p, y) = -\bigl[y \ln \hat p + (1 - y) \ln (1 - \hat p)\bigr].$$

Both are strictly proper: if the event has true probability $p$, the
expected Brier score $p(1 - \hat p)^2 + (1 - p)\hat p^2$ is minimised only at
$\hat p = p$ (differentiate: $-2p(1-\hat p) + 2(1-p)\hat p = 0 \Rightarrow
\hat p = p$), and likewise the expected log score is the cross-entropy, whose
minimum over $\hat p$ is at $p$. A forecaster therefore gains nothing by
shading toward or away from the market. The Brier score is bounded and is
the headline; the log score punishes confident misses without bound, which
is why forecasts are clipped to $[0.01, 0.99]$ before scoring.

## Skill

The market price $q$ at the cutoff is itself a forecast, and the question
the project asks is whether $\hat p$ beats it. The Brier skill score over
the same $N$ markets is

$$\text{BSS} = 1 - \frac{\overline{\text{Brier}}(\hat p)}{\overline{\text{Brier}}(q)},$$

positive when the forecaster is better than the market, 0 when equal,
negative when worse. It is only meaningful on a common set, so the backtest
scores every forecaster on the markets all of them answered and the market
priced.

## Reliability Diagram and Murphy Decomposition

Forecasts are binned on ten equal-width probability intervals. For bin $k$
with $n_k$ forecasts, mean forecast $\bar p_k$ and observed frequency
$\bar y_k$, and base rate $\bar y$ over all $N$ markets, Murphy (1973)
showed

$$\overline{\text{Brier}} = \underbrace{\frac1N \sum_k n_k (\bar p_k - \bar y_k)^2}_{\text{reliability}}
\;-\; \underbrace{\frac1N \sum_k n_k (\bar y_k - \bar y)^2}_{\text{resolution}}
\;+\; \underbrace{\bar y (1 - \bar y)}_{\text{uncertainty}}.$$

The identity is exact when every forecast in a bin equals the bin mean;
with raw forecasts a within-bin variance term remains, which the code
reports as the residual so the identity can be checked (it is non-negative,
and zero in the unit test that places forecasts at bin means).

- **Reliability** is calibration error: lower is better, and a calibrated
  forecaster's is near zero (the unit test draws outcomes from the forecasts
  themselves and checks it stays below 0.01 with 500 draws).
- **Resolution** is how far the bins' observed frequencies sit from the base
  rate: higher is better, it is the information in the forecasts.
- **Uncertainty** is the base rate's own variance, which no forecaster
  controls; weather buckets have a base rate near 0.10 and therefore a low
  Brier score for every forecaster, which is why skill against the market,
  not the raw score, is the comparison.

The reliability diagram plots $\bar y_k$ against $\bar p_k$; the expected
calibration error $\sum_k n_k |\bar p_k - \bar y_k| / N$ summarises its
distance from the diagonal.

## Bankroll Statistics

Once forecasts become bets (see [sizing](sizing.md)), the settled profit
and loss sequence is summarised by `vp.backtest.bankroll`: total return,
maximum drawdown, win rate, profit factor and a per-bet Sharpe ratio, with
a bootstrap confidence interval on the Sharpe ratio and the fraction of
resamples in which it is positive. The bootstrap is the statistic to read:
a forecaster with a positive return but $P(\text{Sharpe} > 0)$ near 0.5 has
not shown edge.

## References

- Brier, G. W. (1950). Verification of forecasts expressed in terms of
  probability. *Monthly Weather Review* 78(1), 1–3.
- Murphy, A. H. (1973). A new vector partition of the probability score.
  *Journal of Applied Meteorology* 12(4), 595–600.
- Gneiting, T. and Raftery, A. E. (2007). Strictly proper scoring rules,
  prediction, and estimation. *JASA* 102(477), 359–378.
