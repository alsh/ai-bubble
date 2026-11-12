# Product Requirements Document: The Canary

**Version:** 2.0
**Type:** Static dashboard and scheduled AI market monitor
**Technology:** Python, GitHub Actions, GitHub Pages, OpenRouter

## 1. Purpose and operating principles

The Canary publishes a daily editorial assessment of structural fragility in the AI investment boom over the next 6–12 months. The score is an editorial index from 0 to 100. It is not a calibrated probability, a crash forecast, or investment advice. Model confidence describes analytical confidence. `data_quality` reports evidence collection completeness independently.

The application uses GitHub Actions as its runtime, repository JSON files as its history store, and GitHub Pages for its static dashboard. It has no application server or database. The dashboard is a single HTML file with no build step. All dynamic text is rendered through safe DOM APIs and `textContent`; it must not use `innerHTML`.

The editorial opinion and experimental Power Exponents diagnostics are separate pipelines. Power Exponents are descriptive research measurements. They do not enter the editorial prompt or score.

## 2. Runtime and model policy

The workflow is `.github/workflows/daily.yml`. It runs on cron `0 22 * * *` (22:00 UTC), after the regular US equity close in both EST and EDT. A manual `workflow_dispatch` trigger is also available. The workflow installs the Python requirements, runs `src/agent.py`, and publishes changed data files.

The agent requests OpenRouter's `~openai/gpt-latest` alias by default. This is an intentional capability-tracking alias, not a fixed model version. `OPENROUTER_MODEL` can override the requested model for controlled testing or rollback. Each editorial record stores the requested model identity and the resolved model identity returned by the provider. Editorial retries use the same requested slug. The agent does not silently fall back to another vendor or model.

LLM requests require `OPENROUTER_API_KEY` in the environment. Do not store API keys in source, prompts, or published artifacts. Unit tests and implementation checks must be offline and must not call paid model APIs.

## 3. Editorial evidence collection

### 3.1 Market packet

`src/agent.py` collects a one-month adjusted daily-price snapshot and fundamentals for `NVDA`, `MSFT`, and `GOOGL`. The market packet can contain latest prices; trailing 5- and 20-session returns; annualized 20-session realized volatility; trailing and forward P/E; revenue growth; and PEG ratios. Return and volatility measurements are scale-free. Missing or invalid provider values are represented as unavailable, not as fabricated numeric values. Legacy NVDA metric aliases remain available for older dashboard and record consumers.

### 3.2 News packet

The agent collects news through the three balanced Bing News RSS queries in `RSS_FEED_URLS`: AI valuation/bubble, AI capital expenditure/data-center spending, and enterprise adoption/revenue/return on investment. It unwraps Bing redirect URLs, deduplicates normalized URLs and titles, and selects at most two fresh articles per query, up to six articles in total. Only when no fresh articles exist across any query, it instead retains at most one deduplicated RSS item per query in feed order so stale or undated news can still provide bounded context in degraded-evidence runs.

For each selected article, the agent extracts publisher attribution from RSS metadata, the title, or the unwrapped URL domain. It attempts full-text extraction with `trafilatura`; when extraction is unavailable, it uses the RSS summary. Article text is limited to 2,500 characters. The packet retains query-topic and URL-domain context. Articles are considered fresh only when their publication timestamp falls within the preceding 48 hours. Unknown dates are not counted as fresh.

The application derives `data_quality` independently from the model's confidence. It records market completeness, fetched and fresh article counts, and the 48-hour freshness window. An entirely empty evidence packet is rejected.

## 4. Editorial record and persistence

New records retain `schema_version: 2` and use `methodology_version: "canary-opinion-v3"`. This preserves compatibility with historical version 2 records while recording the current rubric. The model supplies:

- `score`: a holistic, model-authored assessment of fragility on a 0–100 scale. The score is not a sum of fixed metric-triggered penalties. `0–30` is GREEN (low fragility), `31–69` is YELLOW (watchful or elevated fragility), and `70–100` is RED (high or extreme fragility).
- `confidence`: `LOW`, `MEDIUM`, or `HIGH`, based on analytical evidence, not a substitute for application-owned data-quality status.
- `market_sentiment`: `BEARISH`, `CAUTIOUS`, `MIXED`, `CONSTRUCTIVE`, or `EUPHORIC`, describing observed market tone separately from the fragility score.
- Non-empty `thesis` and `reasoning` strings.
- Non-empty arrays of `risk_factors` and `stabilizing_factors`.
- `change_explanation`, stored with application-owned prior score and score delta under `change`.

The application owns status, date, data-quality metadata, model provenance, and metric collection. It validates model output before persistence. Historical records from earlier schemas remain readable and render with unavailable labels where newer fields do not exist.

Editorial records are partitioned by UTC month in `data/status_history/YYYY-MM.json`. `data/status_history/index.json` lists available months. The agent writes JSON through same-directory temporary files and atomic replacement. If the legacy single file `data/status_history.json` exists, the agent migrates its records into monthly files before removing it after a successful migration.

## 5. Experimental Power Exponents

The default-enabled experimental subsystem is implemented in `src/power_exponents.py` and publishes bounded derived diagnostics to `data/power_exponents.json` for `QQQ`, `SOXX`, `NVDA`, and `SPY`. It publishes no raw price history and retains at most 120 observations per instrument. Its data is stored separately from editorial status history.

The subsystem computes:

- DFA-1 signed-return scaling `H` over a 252-return window, with fit quality and split-scale slopes `h_short` (scales 8–20) and `h_long` (scales 25–63).
- DFA-1 `h_abs` and `h_abs_r_squared` on absolute returns as a descriptive volatility-clustering companion.
- Hill absolute-return tail exponent `alpha` over a 1,000-return window, with `alpha_se` as the idealized i.i.d. standard error and 5%/15% tail-cutoff sensitivity estimates.

These estimates are sensitive to sample size, scale choice, changing regimes, dependent returns, and model assumptions. In particular, `alpha_se` is not a confidence interval under dependent returns, and cutoff sensitivity is not a confidence interval. The dashboard labels the panel experimental and does not present its measurements as forecasts.

When an instrument has available current estimates, the agent may make one bounded AI interpretation request for that instrument, up to four requests for the four instruments. These short interpretations use only that instrument's derived measurements and recent history. They are persisted separately, excluded from the editorial prompt, and cannot change the editorial score. An interpretation failure does not prevent numerical diagnostics from being published.

## 6. Dashboard requirements

`index.html` loads the monthly editorial history index and its listed month files. It supports the legacy single-file history fallback, displays the latest editorial status, thesis, reasoning, risk and stabilizing factors, metrics, and a navigable score-history chart. Users can select historical points and return to current data.

The dashboard preserves the existing `#pe-ratio`, `#rev-growth`, and `#sentiment` elements. It displays available NVDA, MSFT, and GOOGL price, return, realized-volatility, and valuation metrics, plus structured market sentiment. Older records may lack those fields or contain legacy sentiment labels; missing values must render as a clear unavailable value, never as `undefined` or `NaN`.

The Power Exponents panel shows numeric summaries and charts, fit and cutoff information, and available split-scale, absolute-return, and standard-error measurements. It must remain compatible with older artifacts that do not contain `h_short`, `h_long`, `h_abs`, `h_abs_r_squared`, or `alpha_se`. Keep the existing DOM IDs used by tests and integrations. The page must contain exactly one inline application `<script>` element; external library scripts remain loaded by CDN.

## 7. Operational and quality requirements

- Keep editorial scoring separate from Power Exponents measurements and interpretations.
- Use strict JSON serialization that rejects non-finite numeric values, and atomic file replacement for persisted artifacts.
- Preserve historical data. Do not rewrite existing records to make them conform to a newer schema.
- Keep tests deterministic and offline. Do not make paid OpenRouter calls or live network requests from tests.
- Verify dashboard DOM compatibility, including the single-inline-script and no-`innerHTML` constraints.
- Verify changes do not modify `data/` artifacts.
