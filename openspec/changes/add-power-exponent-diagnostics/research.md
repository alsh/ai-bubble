# Critical assessment and data decision

## Decision

Accept a corrected implementation as an **experimental descriptive diagnostic**. Reject the supplied critical-state interpretation, hard-coded crash alert, and claims of established predictive value. Add two separately named exponents and their history. Do not change the editorial score or LLM evidence contract in this version.

## Statistical assessment

1. **Scale invariance is not unique to bubbles.** Brownian motion has self-similar scaling with exponent 0.5. A good DFA log-log fit can therefore occur under the proposed normal-market null. R² is not a test of independent trader horizons becoming synchronized.
2. **Finite-range DFA is not a direct network measurement.** A 6–50-daily-bar fit neither observes minute traders nor proves a diverging correlation length. Under suitable assumptions, the slope estimates a Hurst-type exponent; short memory, nonstationarity, volatility changes, heavy tails, and finite sample size can affect it.
3. **H does not identify the direction of a bubble.** Reversing the sign of every return preserves DFA fluctuations and absolute-return Hill estimates. The proposed measurements can be identical for an upward and a downward path.
4. **The two measurements are not proven orthogonal.** They measure different features of the same returns, but this does not imply statistical independence or zero covariance.
5. **The Hill estimate is not generally unbiased.** The supplied code uses the smallest selected tail value as its cutoff while averaging over a zero log ratio from that same observation. Use a specified standard top-k/order-statistic convention instead. An exact or asymptotic Pareto assumption and threshold choice still need validation.
6. **Twenty extremes are weak support.** For alpha near 3 and k=20, the usual idealized asymptotic standard error alpha/sqrt(k) is about 0.67, before dependence, threshold uncertainty, or model misspecification. A point estimate below 2 does not establish infinite variance in the observed market. Alpha at or below 2 implies divergent variance only for an appropriate unbounded theoretical tail model.
7. **The rolling baseline is not a significance test.** Consecutive 200-return windows share 199 observations. The resulting H readings are strongly dependent. A z score of 2 does not have a justified Gaussian false-alarm probability. Use prior-only baseline values for clearer monitoring semantics, but keep it descriptive.
8. **There is a one-session output-label error.** The supplied loop labels `returns[idx-W:idx]` with `dates[idx]`, although the final included return is at `dates[idx-1]`. It also skips the earliest available full-window output and does not use the final return in the final output.
9. **Input and degenerate-state guards are missing.** Empty outputs fail at `set_index`; too few valid scales fail at `polyfit`; empty nonzero tails fail at indexing. Nonpositive prices, infinities, duplicates, invalid configuration, and constant baselines need explicit handling.
10. **The synthetic example cannot validate crash forecasting.** Smoothing shared shocks deliberately creates short-run serial correlation. It includes neither a crash nor an independently specified trader-network transition. It does not establish long memory, endogenous criticality, or predictive lead time. Its final 200-return window also mixes the 150-observation synthetic herding period with the normal period.
11. **Thresholds are not supported by calibration.** The prose gives R² > 0.985 but the config uses 0.980. No evidence is provided for those cutoffs, H=0.65, or a z=2 alert. Discard the alert rather than choosing a preferred cutoff.

## Data choice for The Canary

| Instrument | Role | Main limitation |
| --- | --- | --- |
| QQQ | Nasdaq-100 technology/growth exposure | Not an AI-only or technology-only index |
| SOXX | Semiconductor-sector exposure | Sector/index composition can change |
| NVDA | Existing AI-hardware bellwether | Single-company news and earnings can dominate |
| SPY | Broad US equity comparison | Overlaps large technology holdings; not an independent experiment |

Use each series separately. Use adjusted close-to-close daily log returns with explicit split/dividend adjustments. Do not use the existing five-day dollar-price standard deviation, the editorial score, news sentiment, pooled price levels, or an arbitrary present-day AI basket.

Fetch approximately five years of daily prices. Use 252 returns for H and 1000 returns for alpha, then retain at most 120 recent diagnostic observations for display. These are practical initial research settings, not statistically optimal or validated alert parameters. Daily scales represent trading-observation aggregation only; they do not provide actual intraday data.

Run after close with a publication buffer. The existing 21:00 UTC schedule coincides with the winter US close, so it is too early to assume a finalized bar. Use 22:00 UTC and reject today's bar before 16:15 New York time in manual runs. No weekend filling, no fabricated zero returns, no silent outlier deletion, and no automatic data repair in the initial estimator.

Yahoo/yfinance access is unofficial. Technical availability does not establish permission to publish or commercially use derived market data. Do not publish raw input history. The operator must verify applicable provider/exchange rights before public deployment.

## Primary sources consulted

- Hill (1975), *A Simple General Approach to Inference About the Tail of a Distribution*: https://doi.org/10.1214/aos/1176343247 . Conditional tail inference, not an assertion that every return sample has a Pareto tail.
- Bhattacharya, Kallitsis, Stoev (2019), *Data-adaptive trimming of the Hill estimator and detection of outliers in the extremes of heavy-tailed data*: https://projecteuclid.org/journals/electronic-journal-of-statistics/volume-13/issue-1/Data-adaptive-trimming-of-the-Hill-estimator-and-detection-of/10.1214/19-EJS1561.full . Includes the standard next-order-statistic Hill convention and sensitivity to extreme observations.
- Ignaccolo, Latka, West (2010), *Detrended fluctuation analysis of scaling crossover effects*: https://doi.org/10.1209/0295-5075/90/10009 . Shows why apparent short-time DFA scaling needs care.
- López, Contreras (2013), *Performance of multifractal detrended fluctuation analysis on short time series*: https://doi.org/10.1103/PhysRevE.87.022918 . Relevant finite-length limitations; this paper concerns multifractal DFA, not a direct calibration of this DFA-1 monitor.
- yfinance history API: https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html . Explicit adjustment flags, inclusive start/exclusive end, daily intervals, and intraday-history limits.
- yfinance adjustment policy: https://ranaroussi.github.io/yfinance/advanced/price_adjustment.html . With auto_adjust=True, Close includes split/dividend adjustment.
- yfinance repair caveats: https://ranaroussi.github.io/yfinance/advanced/price_repair.html . Repair can produce false positives; do not silently apply it to extreme-return estimation.
- Invesco QQQ product description: https://www.invesco.com/qqq-etf/en/home.html . Nasdaq-100 exposure and long fund history.
- iShares SOXX product description: https://www.ishares.com/us/products/239705/ishares-semiconductor-etf . Semiconductor exposure and corporate-action context.
- NYSE market hours and calendars: https://www.nyse.com/markets/hours-calendars . Regular 09:30–16:00 Eastern session, holidays, and early closes.

## Predictive-use gate

A separate study must predefine adverse outcomes and lead times, compare with simple return/volatility baselines, use walk-forward holdouts, account for overlapping windows and repeated threshold searches, and report false alarms, missed events, and lead-time distributions. Include iid Gaussian/heavy-tail, shuffled, short-memory, and volatility-clustered nulls. Do not present a successful synthetic smoke test as evidence that this indicator forecasts crashes.

## Independent numerical checks

A research subagent ran in-memory null experiments with NumPy 2.5.4 and PCG64. These checks support the descriptive-only decision; they are not predictive validation of the implemented monitor.

For DFA, it generated 50,000 independent 252-return windows per null with seed `20260315`. It used **forward-only partitions and ten rounded geometric scales** (8, 10, 13, 16, 20, 25, 32, 40, 50, 63), not the production module's twelve-scale forward/backward configuration. Under iid Gaussian returns, 30.148% of windows had R² >= 0.980; under iid variance-normalized t(3.5) returns, 24.952% did. H >= 0.65 together with R² >= 0.980 occurred in 1.164% and 1.050% respectively. These are individual-window rates before any rolling z-score condition, **not** the full proposed alert's false-alarm rate.

For Hill, seed `20260316`, 50,000 independent 1000-observation samples, and the standard next-order-statistic threshold produced the following median alpha estimates for 5%, 10%, and 15% tail fractions:

| Null | 5% | 10% | 15% |
| --- | --- | --- | --- |
| iid Gaussian | 6.00 | 4.71 | 3.97 |
| iid t(3.5), asymptotic survival exponent 3.5 | 2.96 | 2.68 | 2.47 |

The t(3.5) null has finite variance. The differences show finite-threshold bias and sensitivity; they do not establish that the empirical tails fit a power law. These exploratory numbers were reported by the independent research agent; no Monte Carlo script is retained in this repository. The implementation has separate repeatable numerical reference, Pareto-recovery, causality, and data-contract tests.

Additional full-text methodological references inspected by the research agent:
- Kantelhardt et al. (2001), *Detecting long-range correlations with detrended fluctuation analysis*: https://arxiv.org/abs/cond-mat/0102214 ; https://doi.org/10.1016/S0378-4371(01)00144-3 .
- Clauset, Shalizi, Newman (2009), *Power-Law Distributions in Empirical Data*: https://arxiv.org/abs/0706.1062 ; https://doi.org/10.1137/070710111 .

## Live feed feasibility and deployment gate

A separate research subagent made one read-only yfinance 1.1.0 request on 2026-11-04 for QQQ/SOXX/NVDA/SPY/MSFT/GOOGL, using adjusted daily data from 2025-11-01 through exclusive end 2026-11-05. It received 253 rows dated 2025-11-03 through 2026-11-04; all six Close columns were finite and non-null. The index was timezone-naive and the multi-symbol response used a field/ticker MultiIndex. This checks one-year availability only. The response included the current date, so a finite returned Close must not be assumed to be a finalized session close. Production code uses per-symbol history and excludes incomplete sessions.

Five-year retrieval and future service reliability were not live-verified. No raw response was saved to the repository and no model call was made. Yahoo's [Terms of Service](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html) §2(d)(ix) say automated access or collection requires express, prior permission; §2(h) restricts reproduction, distribution, and derivative works. The [yfinance README](https://github.com/ranaroussi/yfinance/blob/e2f6104164b70085556fe2f8e194cf3ca18550f5/README.md) says the API is intended for personal use only. We have not established that these terms permit a public GitHub dashboard to publish derived indicators. This is not a legal determination. Keep scheduled collection disabled unless permission that covers automated collection and public display is obtained, or use a source with an applicable license.

## Implementation verification

The parent repeated the offline Python/Node-stub tests after implementation and corrected sample-window labels, browser-side aging of an existing artifact, and retention bounds for failed symbols. The live indicator artifact was not generated or deployed. Active LSP diagnostics reported no findings but returned inconclusive coverage for all five requested files; this is **not** confirmation of clean language-server checks. The dashboard was checked with DOM/Chart stubs, not visually rendered in a browser.
