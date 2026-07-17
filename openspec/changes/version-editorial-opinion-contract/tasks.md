## 1. Contract and Test Foundation

- [x] 1.1 Add tracked test fixtures for legacy history, a valid version-2 model response, malformed responses, degraded evidence, and corrupt history.
- [x] 1.2 Add unit tests for score validation, confidence and required-field validation, status boundaries, prior-score selection, delta calculation, and baseline behavior.
- [x] 1.3 Add unit tests proving history parse/validation failures leave the destination unchanged and mixed legacy/version-2 history appends correctly.

## 2. Editorial Analysis Contract

- [x] 2.1 Define constants and focused helpers for schema version 2, methodology `canary-opinion-v2`, score-derived status, and validated model-authored fields.
- [x] 2.2 Replace the additive Bubble Algorithm prompt with the stable 6–12 month editorial question, analytical lenses, balanced-evidence instructions, and explicit JSON output contract.
- [x] 2.3 Load compact prior context from valid history entries and include the prior score/thesis plus no more than seven recent scores in the prompt.
- [x] 2.4 Compute application-owned status and change metadata while preserving the model-authored change explanation.

## 3. Model Selection and Provenance

- [x] 3.1 Make `~openai/gpt-latest` the default requested model and add a documented environment override for testing or rollback.
- [x] 3.2 Replace the cross-vendor fallback list with bounded retries of the same requested model and ensure exhausted retries fail without persistence.
- [x] 3.3 Capture and validate `completion.model`, then persist requested model, resolved concrete model, and methodology provenance.
- [x] 3.4 Add tests for default selection, configured override, transient retry success, missing resolved identity, and exhausted retries.

## 4. Data Quality and Persistence

- [x] 4.1 Compute market-data completeness, fetched article count, fresh article count, and an overall complete/degraded state independently of model output; choose and document the article freshness window.
- [x] 4.2 Reject an entirely empty evidence packet while permitting and marking partially degraded evidence.
- [x] 4.3 Build the version-2 entry with a timezone-aware UTC timestamp and legacy-compatible date, score, status, reasoning, and metrics fields.
- [x] 4.4 Replace corrupt-history reset behavior and direct writes with strict JSON-array loading and same-directory atomic replacement.

## 5. Static Dashboard

- [x] 5.1 Add version-aware rendering that preserves the current legacy view and displays v2 thesis, confidence, update time, score delta, and movement explanation.
- [x] 5.2 Display risk factors separately from stabilizing factors and show independent data-quality state and collection counts.
- [x] 5.3 Display requested/resolved model and methodology metadata and add a stale-analysis warning using a documented freshness threshold.
- [x] 5.4 Replace persisted/external-value `innerHTML` rendering with text-safe DOM construction and verify markup-like content remains inert.
- [x] 5.5 Filter the trend to valid numeric scores from mixed-schema history and retain the latest 30 valid points.

## 6. Operations and Documentation

- [x] 6.1 Update README and PRD documentation to describe the editorial opinion, 6–12 month horizon, confidence versus data quality, version-2 methodology, and OpenRouter alias semantics.
- [x] 6.2 Ensure the existing single GitHub Action, Python process, JSON file, and GitHub Pages topology remains unchanged and requires no new service.
- [x] 6.3 Run the complete automated test suite and perform fixture-based end-to-end generation and dashboard checks for both legacy and version-2 latest records.
- [x] 6.4 If credentials are available, perform one non-persisting live request to verify that `~openai/gpt-latest` resolves and the concrete model identifier is captured; otherwise document the unverified live integration.

Live integration note: no `OPENROUTER_API_KEY` was available in this environment, so the non-persisting alias-resolution request remains unverified. Mocked provenance and retry tests pass.
