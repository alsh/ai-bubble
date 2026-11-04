# Tasks

## 1. Deterministic exponent engine

- [x] 1.1 Add the separate calculation module and explicit NumPy dependency; verify that imports work in the project environment without network access.
- [x] 1.2 Implement guarded DFA-1 with documented partitions/scales and 252-return default; verify against a small independent least-squares reference and constant/short/non-finite input tests.
- [x] 1.3 Implement standard order-statistic Hill alpha with 1000-return default, minimum tail count, and 5/10/15% sensitivity; verify hand-calculated order-statistic cases, zero/tied tails, and seeded Pareto recovery.
- [x] 1.4 Implement causal rolling H/alpha points, one/five-observation H changes, and preceding-30 baseline deviation; verify exact first/last date alignment and fixed-input prefix invariance for all output fields.
- [x] 1.5 Document estimator meanings, distinct horizons, finite-sample limits, threshold sensitivity, and the absence of a crash alert in `docs/power-exponents.md`; verify equations and defaults against the implementation.

## 2. Collection, provenance, and publication

- [x] 2.1 Collect explicit adjusted daily history for QQQ/SOXX/NVDA/SPY with timeouts and version/settings provenance; verify provider kwargs and each instrument's independent failure behavior with mocks.
- [x] 2.2 Exclude incomplete/future bars using New York time and reject damaged inputs without forward-fill; verify pre/post-close, both seasonal UTC offsets, weekends, duplicate dates, invalid prices, and conspicuous gap/staleness handling.
- [x] 2.3 Build and atomically publish strict bounded indicator JSON with 120 points per instrument and reconstruction metadata; verify artifact size bounds, JSON null handling, failure-state dates, and destination preservation/temp cleanup on failed replacement.
- [x] 2.4 Integrate optional indicator publication into the daily agent without adding indicators to market metrics or the LLM prompt; verify editorial behavior survives indicator failure and existing contract tests pass.
- [x] 2.5 Move cron to 22:00 UTC and update schedule/data-use documentation; verify workflow references and README commands, including a no-OpenRouter way to exercise the indicator path.

## 3. Dashboard indicator panel

- [x] 3.1 Add an independent text-safe Power exponents panel with instrument selection, dates, settings, H/alpha summaries, changes, R², tail counts, and sensitivity; verify rendered values and explicit experimental wording with fixture data.
- [x] 3.2 Add separate H and alpha history charts with 30/120-point controls, data-date/sample tooltips, null gaps, and the descriptive H=0.5 reference; verify no risk-score axis coupling or forced [0,1] H range.
- [x] 3.3 Load indicator JSON independently and show missing/stale/error states without affecting editorial navigation; verify legacy-only, unavailable, partial-failure, all-zero, and populated artifacts using deterministic frontend checks.
- [x] 3.4 Document independent diagnostic-history behavior and methodology access; verify the page identifies vendor-reconstructed history and does not imply historical point-in-time forecasts.

## 4. Integration verification

- [x] 4.1 Run Python/JavaScript syntax checks and all offline tests; verify compilation, dashboard-script execution, and 45 tests pass. Parent active LSP probes returned no findings but inconclusive coverage for all five paths; no clean LSP result is claimed.
- [x] 4.2 Check the dashboard with populated and missing artifacts, using a rendered browser if available or a repeatable DOM/Chart stub test otherwise; verify original Older/Newer/Show current data controls still work.
- [x] 4.3 Validate the OpenSpec change strictly and review the diff; verify no unrelated change files, existing history rewrites, generated live-data commits, deployment, or paid model calls occurred.

## Workflow follow-up

- Review the completed implementation before archive or deployment.
- Confirm provider permissions for public derived diagnostics before enabling production publication.
- Perform the separately specified walk-forward validation before considering alerts or editorial-score integration.
