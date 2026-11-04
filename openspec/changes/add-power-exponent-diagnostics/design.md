# Design

## Context

See `proposal.md` for motivation. The application has one Python agent, monthly editorial JSON files, a static Chart.js page, and a GitHub Actions job. The current five-day market fetch cannot support scaling estimation. Existing schema-v2 market metrics are flat and normalized as scalars, so nested diagnostic objects must not be inserted into that map. The existing model-directed-research change is unrelated and must remain untouched.

## Goals / Non-Goals

**Goals:** Deterministic causal measurements, a useful initial history graph, explicit data quality, bounded repository growth, and unchanged editorial behavior.

**Non-Goals:** Crash prediction, trader-network inference, cross-asset contagion measurement, intraday/multi-frequency collection, automatic alert thresholds, a backtest claiming forecasting performance, or new LLM input.

## Decisions

### 1. Two exponents, not a single risk index

Call the feature **Power exponents (experimental)**. H is the finite-range DFA-1 return-scaling slope; alpha is the survival-tail exponent of absolute returns. They are not interchangeable or proven orthogonal. H is not universally a Hurst exponent under arbitrary nonstationary/heavy-tailed processes. R² is fit quality only. Brownian motion itself has scaling, so a good straight-line fit does not establish a critical transition.

Do not copy the supplied critical alert or its 0.65/0.980/2 thresholds. Retain a 0.5 reference for H only as a descriptive iid benchmark, not a normal/safe classification. No risk colors or infinite-variance claim are derived from alpha.

### 2. Instrument-level adjusted daily returns

Use QQQ as a Nasdaq-100 technology/growth proxy, SOXX as a semiconductor-sector proxy, NVDA as the existing AI hardware bellwether, and SPY as a broad-market comparison. None is an AI-only index. Do not manufacture a present-day equally weighted historical AI basket: that creates arbitrary weighting and survivorship problems. Existing MSFT and GOOGL snapshot collection remains unchanged.

Fetch approximately five years of daily history per instrument with explicit `auto_adjust=True`, `interval='1d'`, `prepost=False`, `repair=False`, and a finite timeout. Do not silently repair or trim extreme but valid returns: those are the observations under study. Record adjustment settings and yfinance version. Do not fetch fundamentals for these new series.

Sort dates; reject duplicate, nonpositive, non-finite, and out-of-order input rather than silently joining across damaged rows. Use `log(P).diff()`, not rounded prices, dollar-price standard deviations, news sentiment, or the editorial score. Do not forward-fill or add weekend zero returns. Exchange holidays are not missing data. Flag conspicuous feed gaps and stale input; an exact exchange-calendar dependency is not required for v1, but document conservative session handling and distinguish it from full calendar validation.

Use New York time. A conservative completion cutoff of 16:15 local time excludes the current session before close plus a publication buffer. This also safely delays early-close sessions until 16:15. Schedule at 22:00 UTC, safely after regular close year-round. Label every point with the final return session it actually includes.

### 3. Separate statistical horizons

Default DFA: 252 returns, 12 unique logarithmic integer scales from 8 to 63 bars, at least four nonoverlapping boxes per scale, linear local detrending. Include forward and backward partitions when they use different origins, without presenting them as independent samples. Require at least six valid scales and guard zero fluctuation/zero regression variance. Report actual scales, segment counts, and fitted R². The short range is a finite-range diagnostic, not evidence of asymptotic scaling.

Default Hill: 1000 returns with top 10% positive absolute observations as the main estimate, and 5%/15% sensitivity estimates. Use the next order statistic below the top k as the threshold: alpha = k / sum(log(X_i / X_(k+1))). Require at least 50 tail observations and k < positive count; expose actual k and x_min. Guard ties and zero log sums. Sensitivity range is not a confidence interval. Do not assert unbiasedness or Pareto-model validity. A longer window trades reactivity for lower sampling noise and still needs tail-model validation.

For H dynamics, compute differences over one and five trading observations. Compute baseline deviation from the preceding 30 valid, consecutive H readings, excluding the current reading, using sample standard deviation. It is a descriptive standardized deviation, not a Gaussian significance test. Missing/constant baselines produce null. Causality tests must include these fields.

### 4. Bounded indicator artifact and optional recorded snapshot

Create a small dedicated module, such as `src/power_exponents.py`, with pure estimators separated from provider collection and JSON presentation. Add NumPy explicitly to `requirements.txt`.

Write `data/power_exponents.json` with an artifact version, indicator methodology version, UTC generation/retrieval dates, settings, a warning, and one object per instrument. Store at most the last 120 completed-session diagnostic points per instrument, with enough prehistory to initialize rolling H baselines. Each point contains H, R², alpha, sensitivity values, H changes/deviation, counts and explicit unavailable states. No raw prices or returns are published. Reconstructed history is labeled as calculated from the current vendor-history retrieval, not a point-in-time backtest.

Use same-directory temporary files and strict JSON (`allow_nan=False`) followed by atomic replacement. Reuse the existing writer if practical without circular imports. Optional application-owned latest diagnostic snapshots can be added under a top-level `power_exponents` field in new editorial entries, never inside normalized flat `metrics`. Preserve old records. The live graph uses the independent artifact and states it is independent of editorial-history selection.

Collection failure is isolated by symbol. If retaining prior points, carry their original retrieval/data dates and mark them stale; otherwise publish an unavailable object. Do not replace a failed symbol with a fresh-looking empty/normal result. Indicator collection/publication errors do not abort the existing editorial process. Integrate without paid model calls, migrations, or historical opinion backfill. Provide a deterministic/offline entry point or test fixture for indicator publication without invoking OpenRouter.

### 5. Separate frontend measurements

Add an instrument selector, H and alpha numeric summaries, H one/five-observation changes, baseline deviation, R², input sample/tail counts, adjustment settings, and actual data-as-of date. Use separate H and alpha line charts; do not place them on the 0–100 editorial risk axis. Show missing values as gaps (`spanGaps: false`), with no zero substitution and no arbitrary H clamp to [0,1]. Include per-point dates and sample information in tooltips. Add a 30/120-observation history choice or similarly bounded navigation.

Load indicator JSON independently so a missing/invalid artifact cannot prevent editorial rendering. Preserve existing Older/Newer/Show current data behavior. Use text-safe DOM APIs and provide textual unavailable/stale messages. Add a methodology link. Explicitly identify initial historical diagnostics as reconstructed from vendor history.

## Risks / Trade-offs

- [False interpretation as a crash signal] → Prominent experimental wording, no alert, and no LLM/score coupling.
- [Short-scale finite-sample bias and short-memory persistence] → Show parameters and R² without inferential claims; test iid and short-memory nulls. A true predictive study is a separate gate.
- [Noisy tail estimates and model misspecification] → Longer tail window, minimum k, threshold sensitivity, no variance diagnosis, and no unsupported confidence interval.
- [Long tail window responds slowly] → Expose its distinct 1000-return horizon; do not imply that it measures today's tail distribution.
- [Vendor history changes] → Record retrieval/settings/version and label reconstructed history; prefix invariance applies to fixed inputs, not future vendor revisions.
- [Missing exchange sessions] → Never fill, flag suspicious gaps, and document that conservative timing is not a full exchange-calendar audit.
- [Yahoo access or use restrictions] → Document that yfinance is unofficial and access is not a redistribution license. The operator must verify permission for public derived-data use before production publication; do not claim legal clearance or publish raw input history.
- [Two independently atomic JSON stores] → They need not be a transaction: dashboard shows their own dates and loads independently. Preserve existing editorial-write semantics.

## Migration Plan

No existing JSON rewrite is needed. The dashboard must tolerate absence of the new artifact. After deterministic tests and local UI checks, the normal scheduled run can generate the first artifact using the selected provider, subject to operator data permissions. Do not commit generated live data, deploy, or invoke OpenRouter during implementation. Rollback removes the optional panel/module integration; legacy and v2 editorial history remains intact.

## Validation gate for predictive use

Before any future alert or score integration, define outcomes and lead times in advance; use broad historical samples and simple return/volatility baselines; include iid heavy-tail, shuffled, AR, and volatility-clustered nulls; use walk-forward holdouts and account for overlapping windows/multiple testing. Report false alarms, missed events, lead time, calibration where applicable, and sensitivity to windows/scales/thresholds. The supplied synthetic example is only a numerical smoke test, not validation of market-crash prediction.
