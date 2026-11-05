# Power exponents (experimental)

This panel shows two **descriptive market measurements**. They are not crash predictors, probabilities, measures of trader synchronization, or investment advice. They do not affect The Canary's editorial score or its LLM prompt.

The selected series are measured separately:

- **QQQ**: Nasdaq-100 growth/technology exposure. It is not an AI-only index.
- **SOXX**: semiconductor-sector exposure. Its holdings and index composition can change.
- **NVDA**: a single AI hardware bellwether. Company-specific events can dominate.
- **SPY**: a broad US market comparison that overlaps with large technology companies.

These funds are proxies. They do not represent a pure or stable portfolio of AI companies. Do not compare them as independent experiments, pool their price levels, or interpret their correlation as a causal AI-market effect.

## Inputs and provenance

The collector requests five years of Yahoo Finance daily history through the unofficial `yfinance` client. It requests `interval="1d"`, `auto_adjust=True`, `prepost=False`, and `repair=False`. Thus daily `Close` is adjusted for splits and dividends according to yfinance's adjustment behavior. Returns are log differences of adjusted closing prices. The collector does not forward-fill dates, add weekend zero returns, clip valid extremes, or silently repair prices.

The artifact records the instrument, source/client, adjustment settings, methodology version, retrieval time, last session date, and whether the history is reconstructed. Historical chart points are recalculated from the provider's current historical response. A provider can revise prices or corporate-action adjustments. These points are **not archived point-in-time forecasts** and may change when the source history changes. The dashboard does not publish raw closes or returns.

The regular-session workflow runs at 22:00 UTC, after the US close in both standard and daylight-saving time. A manually started run excludes today's bar before 16:15 America/New_York. This conservative cutoff also excludes early-close sessions until 16:15; it is not an exchange-calendar calculation. The actual session date in the artifact is authoritative. The dashboard also marks old input stale if an existing artifact stops updating. An input gap longer than seven calendar days is flagged, but ordinary weekends and exchange holidays are not filled with artificial prices.

## DFA-1 return-scaling exponent H

For adjusted prices `P_t`, compute signed log returns:

`r_t = log(P_t) - log(P_(t-1))`.

The current estimate uses the most recent **252 return observations**. It subtracts the window mean, integrates the centered returns into a profile, and removes a local linear trend in boxes of **12 unique rounded logarithmic scales from 8 through 63 trading observations**. At each scale, at least four boxes are required. A second partition from the right edge is included when it has a different origin. These two partitions can overlap each other; they are not independent samples. The slope of `log(F(tau))` against `log(tau)` is reported as `H`; the corresponding log-log `R²` is reported only as fit quality. At least six valid scales are required.

A value around **0.5** is a reference for ideal independent finite-variance returns. Values above or below it do not alone establish persistence, mean reversion, a bubble, or a safe regime. Short-memory dependence, volatility changes, heavy tails, trends, finite samples, scale choices, and the selected series affect the estimate. Ordinary Brownian motion is itself scale-invariant, so a high `R²` is not evidence of a critical transition.

The dashboard reports one- and five-observation changes in H. Its standardized deviation compares the current H with the preceding 30 consecutive valid H values, using their sample standard deviation. This value is descriptive, not a significance test: rolling windows overlap and the observations are dependent. Null output means an estimate or baseline is unavailable or degenerate; it is never plotted as zero.

## Hill survival-tail exponent alpha

The current estimate uses the most recent **1000 absolute log-return observations**. It selects the top 10% of positive observations, with a minimum tail count of 50. If `X_(1) <= ... <= X_(n)` are the sorted positive absolute returns and `k` is the selected tail count, it uses the next lower order statistic `x_min = X_(n-k)` and reports:

`alpha = k / sum(log(X_i / x_min))` for the `k` largest observations.

The artifact also reports estimates using 5% and 15% cutoffs. This threshold sensitivity range is **not** a confidence interval. The estimate can be unavailable when the input has too few positive returns or zero log exceedances. Finite samples, dependence, cutoff selection, and failure of the Pareto-tail model can materially affect alpha. A value at or below 2 does not prove that the observed market has infinite variance; that mathematical implication applies only under an appropriate unbounded theoretical tail model.

The 1000-observation tail window is deliberately different from the 252-observation DFA window. It is slower and more sample-intensive. This panel does not treat alpha as a measure of today's tail risk.

## Validation limits and references

This version has numerical and data-contract tests, not a historical crash-prediction validation. The synthetic example supplied with the original proposal smooths shared shocks and does not simulate or predict a crash. Before any alert or score integration, a separate study must define outcomes and lead times in advance, compare with simple baselines, use walk-forward holdouts, account for overlapping windows and repeated threshold searches, and report false alarms, misses, and lead times. It should include iid, heavy-tail, shuffled, short-memory, and volatility-clustered nulls.

Method references:

- B. M. Hill (1975), [A Simple General Approach to Inference About the Tail of a Distribution](https://doi.org/10.1214/aos/1176343247).
- S. Bhattacharya, M. Kallitsis, S. Stoev (2019), [Data-adaptive trimming of the Hill estimator and detection of outliers](https://projecteuclid.org/journals/electronic-journal-of-statistics/volume-13/issue-1/Data-adaptive-trimming-of-the-Hill-estimator-and-detection-of/10.1214/19-EJS1561.full).
- M. Ignaccolo, M. Latka, B. J. West (2010), [Detrended fluctuation analysis of scaling crossover effects](https://doi.org/10.1209/0295-5075/90/10009).
- J. L. López and J. G. Contreras (2013), [Performance of multifractal detrended fluctuation analysis on short time series](https://doi.org/10.1103/PhysRevE.87.022918). This concerns multifractal DFA, not a calibration of this DFA-1 monitor.
- [yfinance daily-history reference](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html), [adjustment behavior](https://ranaroussi.github.io/yfinance/advanced/price_adjustment.html), and [price-repair limitations](https://ranaroussi.github.io/yfinance/advanced/price_repair.html).
- Product context: [Invesco QQQ](https://www.invesco.com/qqq-etf/en/home.html), [iShares SOXX](https://www.ishares.com/us/products/239705/ishares-semiconductor-etf), and [NYSE hours/calendars](https://www.nyse.com/markets/hours-calendars).
