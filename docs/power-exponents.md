# Power exponents (experimental)

This panel shows **descriptive market measurements**. They are not crash predictors, probabilities, measures of trader synchronization, or investment advice. They do not affect The Canary's editorial score or its editorial LLM prompt.

Daily diagnostic artifacts use `power-exponents-dfa1-hill-v2`. The additive point fields keep the artifact schema at version 1. Separate AI explanations use `power-exponents-interpretation-v2`.

The selected series are measured separately:

- **QQQ**: Nasdaq-100 growth/technology exposure. It is not an AI-only index.
- **SOXX**: semiconductor-sector exposure. Its holdings and index composition can change.
- **NVDA**: a single AI hardware bellwether. Company-specific events can dominate.
- **SPY**: a broad US market comparison that overlaps with large technology companies.

These funds are proxies. They do not represent a pure or stable portfolio of AI companies. Do not compare them as independent experiments, pool their price levels, or interpret their correlation as a causal AI-market effect.

## Short AI-generated interpretations

The daily workflow makes one separate OpenRouter request per instrument with available estimates, up to four additional requests per run. It uses `OPENROUTER_API_KEY` and the same `OPENROUTER_MODEL` setting as the editorial analysis. Each request has a 60-second timeout and no automatic retries. This adds API cost and can add up to approximately four minutes of waiting time.

For each instrument, the v2 prompt sends the full latest point and a compact projection of up to 30 recent observations. The projection keeps `date`, `h`, `h_r_squared`, `h_short`, `h_long`, `h_abs`, `h_baseline_z`, `alpha`, `alpha_se`, `alpha_k`, and `alpha_x_min`; the full latest point retains detailed metadata such as scale and segment counts. The input does not contain raw prices, news, or the editorial score. The instruction requests 90–150 words in at most three short paragraphs. Responses longer than 180 words or 2400 characters are rejected. The text should explain H, fit quality, fitted tail thickness, recent changes, and cutoff sensitivity where data is available. It must not turn descriptive estimates into crash forecasts, safety claims, or significance tests. These instructions reduce unsupported claims; they do not guarantee numerical or scientific correctness.

Each instrument record can have an `interpretation` object. An available interpretation records `text`, `session_date`, the recent-history date range and observation count, generation time, prompt version, estimator version, and requested/resolved model identities. The artifact is published atomically after generation. A failed or invalid response sets that instrument's interpretation to unavailable without removing its numerical diagnostics or stopping the other requests. An instrument with stale retained data keeps its previous interpretation, if present; no new request is made for it.

The text widget is below the power graphs. It follows the instrument selector but always describes the latest recorded session and its recent history. Selecting an older chart point or changing the chart range does not change the interpretation period. The widget states this scope, marks retained or aged data stale, and hides text whose session does not match the instrument's latest session. Old artifacts without interpretations remain valid. Model text is displayed as plain text, not HTML.

## Inputs and provenance

The collector requests five years of Yahoo Finance daily history through the unofficial `yfinance` client. It requests `interval="1d"`, `auto_adjust=True`, `prepost=False`, and `repair=False`. Thus daily `Close` is adjusted for splits and dividends according to yfinance's adjustment behavior. Returns are log differences of adjusted closing prices. The collector does not forward-fill dates, add weekend zero returns, clip valid extremes, or silently repair prices.

The artifact records the instrument, source/client, adjustment settings, methodology version, retrieval time, last session date, and whether the history is reconstructed. Historical chart points are recalculated from the provider's current historical response. A provider can revise prices or corporate-action adjustments. These points are **not archived point-in-time forecasts** and may change when the source history changes. The dashboard does not publish raw closes or returns.

The regular-session workflow runs at 22:00 UTC, after the US close in both standard and daylight-saving time. A manually started run excludes today's bar before 16:15 America/New_York. This conservative cutoff also excludes early-close sessions until 16:15; it is not an exchange-calendar calculation. The actual session date in the artifact is authoritative. The dashboard also marks old input stale if an existing artifact stops updating. An input gap longer than seven calendar days is flagged, but ordinary weekends and exchange holidays are not filled with artificial prices.

## DFA-1 return-scaling exponent H

For adjusted prices `P_t`, compute signed log returns:

`r_t = log(P_t) - log(P_(t-1))`.

The current estimate uses the most recent **252 return observations**. It subtracts the window mean, integrates the centered returns into a profile, and removes a local linear trend in boxes of **12 unique rounded logarithmic scales from 8 through 63 trading observations**. At each scale, at least four boxes are required. A second partition from the right edge is included when it has a different origin. These two partitions can overlap each other; they are not independent samples. The slope of `log(F(tau))` against `log(tau)` is reported as `H`; the corresponding log-log `R²` is reported only as fit quality. At least six valid scales are required.

The method also reports `h_short`, the log-log slope over usable scales from **8–20 trading days**, and `h_long`, the slope over usable scales from **25–63 trading days**. Each sub-slope is available only when at least three scales in its range pass the validity checks. These extra slopes do not change `H`, its `R²`, the usable scales, or their segment counts.

The long-scale slopes need extra caution. In a 252-return window, scales 43, 52, and 63 have only 5, 4, and 4 boxes per partition, respectively. Scale 63 divides the window exactly, so it uses only one partition. At scales 43 and 52, the forward and reverse partitions overlap; they are not independent samples. These small counts increase variance. A shift in one quarter can also change the long-scale fit. Compare `h_long` with `h_short`, overall `H`, and fit quality. Do not treat a difference as proof of long-range dependence or a lasting regime change.

The method also runs DFA-1 on absolute returns `|r_t|` and reports `h_abs` and its fit-quality measure, `h_abs_r_squared`. This is a descriptive companion for volatility clustering. Signed daily returns often have H near **0.5**, while return magnitudes can show persistent behavior. A higher `h_abs` does not predict return direction or future volatility.

A value around **0.5** is a reference for ideal independent finite-variance returns. Values above or below it do not alone establish persistence, mean reversion, a bubble, or a safe regime. Short-memory dependence, volatility changes, heavy tails, trends, finite samples, scale choices, and the selected series affect the estimate. Ordinary Brownian motion is itself scale-invariant, so a high `R²` is not evidence of a critical transition.

The dashboard reports one- and five-observation changes in H. Its standardized deviation compares the current H with the preceding 30 consecutive valid H values, using their sample standard deviation. This value is descriptive, not a significance test: rolling windows overlap and the observations are dependent. Null output means an estimate or baseline is unavailable or degenerate; it is never plotted as zero.

## Hill survival-tail exponent alpha

The current estimate uses the most recent **1000 absolute log-return observations**. It selects the top 10% of positive observations, with a minimum tail count of 50. If `X_(1) <= ... <= X_(n)` are the sorted positive absolute returns and `k` is the selected tail count, it uses the next lower order statistic `x_min = X_(n-k)` and reports:

`alpha = k / sum(log(X_i / x_min))` for the `k` largest observations.

The artifact also reports `alpha_se = alpha / sqrt(k)`, an idealized i.i.d. Pareto reference standard error. It understates uncertainty when returns have GARCH-like dependence or when the Pareto model is misspecified. It does not account for cutoff choice and is not a model-robust confidence interval. The artifact also reports estimates using 5% and 15% cutoffs. This threshold sensitivity range is **not** a confidence interval; it describes a different source of uncertainty from `alpha_se`. The estimate and its standard error can be unavailable when the input has too few positive returns or zero log exceedances. Finite samples, dependence, cutoff selection, and failure of the Pareto-tail model can materially affect alpha. A value at or below 2 does not prove that the observed market has infinite variance; that mathematical implication applies only under an appropriate unbounded theoretical tail model.

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
