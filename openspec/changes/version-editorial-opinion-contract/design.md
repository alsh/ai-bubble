## Context

The Canary is a single-process daily publisher: GitHub Actions runs `src/agent.py`, the agent collects Yahoo Finance and news data, asks an OpenRouter model for an opinion, appends JSON to Git, and the static dashboard renders it. This topology is intentionally inexpensive and operationally simple.

The current prompt describes four weighted rules but also asks the model to exercise broader judgment. Production history shows the model inventing adjustments and sometimes returning a score, status, and prose conclusion that disagree. The model fallback chain can also switch vendors without recording which model authored an entry. Existing history must remain usable and the project must not gain a service, database, build system, or second scheduled process.

## Goals / Non-Goals

**Goals:**

- Make the score explicitly and consistently a model-authored editorial opinion.
- Give that opinion a stable subject and 6–12 month horizon.
- Preserve enough structure, provenance, and prior context to interpret the time series.
- Use OpenRouter's current OpenAI GPT flagship alias by default and record the resolved concrete model.
- Validate structural integrity without replacing model judgment with application scoring.
- Keep existing GitHub Actions, flat JSON, and static Pages operation.
- Render both legacy and version-2 history without rewriting historical entries.

**Non-Goals:**

- Calibrate the score as a probability or investment recommendation.
- Implement a deterministic weighted risk formula.
- Add a database, backend API, queue, framework, or additional model call.
- Redesign the market/news collection strategy beyond the minimum freshness and completeness metadata needed by this contract.
- Re-score or migrate existing historical opinions.
- Guarantee that OpenRouter's newest GPT is objectively best for this domain.

## Decisions

### 1. Version the persisted opinion envelope

New records will carry `schema_version: 2` and `methodology_version: "canary-opinion-v2"`. The version-2 envelope will contain:

- `date`: timezone-aware UTC timestamp;
- `score`: model-authored integer from 0 through 100;
- `status`: application-derived `GREEN`, `YELLOW`, or `RED`;
- `confidence`: model-authored `LOW`, `MEDIUM`, or `HIGH`;
- `thesis`: concise overall judgment;
- `reasoning`: fuller explanation retained as the dashboard's detailed narrative and for legacy field continuity;
- `risk_factors` and `stabilizing_factors`: non-empty string lists;
- `change`: application-computed `previous_score` and `delta`, plus the model-authored explanation;
- `data_quality`: collection completeness and article counts computed by the application;
- `model`: requested alias and concrete resolved model;
- `metrics`: the raw market snapshot plus model-selected sentiment/headline fields.

The application, not the model, adds derived and observed metadata after validating model-authored fields. This prevents the model from contradicting arithmetic or claiming provenance it cannot know.

Alternative considered: overwrite the existing schema. Rejected because mixed historical data already exists and must remain renderable without a migration.

### 2. Treat analytical checks as lenses, not additive rules

The prompt will define one question: how fragile the AI investment boom is to a meaningful correction in the next 6–12 months. Valuation, investment efficiency and financing, adoption, hardware demand, concentration, price behavior, and stabilizing evidence are lenses the model must consider. They will not have fixed weights.

The prompt will explicitly permit holistic judgment but require the model to reconcile its numeric score with its thesis and explain material movement from the previous opinion.

Alternative considered: retain the four fixed weights and permit an editorial overlay. Rejected because it creates two competing scores and reproduced the current ambiguity.

### 3. Derive categorical status from the model's score

The model will not return `status`. After validating `score`, the application will derive `GREEN` for 0–30, `YELLOW` for 31–69, and `RED` for 70–100. This is presentation logic, not a second opinion.

Alternative considered: continue asking the model for both fields and validate their agreement. Rejected because status contains no information beyond score and introduces avoidable failure.

### 4. Supply compact, bounded historical context

The prompt will include the prior valid opinion's score and thesis and a seven-entry score trend. It will instruct the model to reassess independently, use prior opinion only as context, and explain material changes. The full archive and prior long-form reasoning will not be sent.

If no prior valid score exists, the analysis will be identified as a baseline and no fabricated delta will be stored.

Alternative considered: omit history to avoid anchoring. Rejected because daily variation then lacks interpretable continuity. Bounded context and explicit independent reassessment balance continuity against anchoring.

### 5. Default to `~openai/gpt-latest` and preserve analyst identity

The requested model will default to `~openai/gpt-latest`, optionally configurable through an environment variable for controlled testing or rollback. On success, the application will persist both the requested slug and `completion.model`, which OpenRouter reports as the concrete serving model.

Transient failures will retry the same requested alias with bounded attempts. Persistent failure will exit without appending history. The agent will not silently switch to Gemini, Llama, or another OpenAI family.

Alternative considered: retain the broad fallback list for maximum run completion. Rejected because undocumented analyst changes damage an opinion time series more than an explicit missing day.

### 6. Validate structure and write atomically

Before persistence, the application will verify required fields, exact primitive/container types, score and confidence domains, and non-empty explanatory content. It will compute status and change arithmetic itself. Existing history must parse as a JSON array; corrupt history will fail without replacement.

The updated JSON will be written to a temporary file in the same directory and atomically replaced. A validation or write failure will leave the prior history intact.

No schema library will be added unless implementation demonstrates that hand-written validation is materially less clear; the contract is small enough to validate with the standard library.

### 7. Compute data quality independently of model opinion

The collector will create a compact data-quality summary from observable facts, including market-data completeness, fetched article count, and fresh article count using a documented freshness window. The model can use this information when assigning confidence, but unavailable evidence does not mechanically lower the risk score.

The run may continue with degraded non-critical inputs, but the saved entry and dashboard must identify degradation. A completely absent evidence packet must fail rather than publish a confident opinion.

### 8. Progressively enhance the static dashboard

The dashboard will detect `schema_version`. For version-2 entries it will show score-derived status, confidence, update time/freshness, score delta and explanation, risk and stabilizing factors, and requested/resolved model metadata. For legacy entries it will retain current rendering and mark unavailable version-2 metadata as legacy rather than inventing values.

All external and model-derived strings will be inserted with text-safe DOM APIs rather than `innerHTML`. The dashboard remains a single static HTML file with no build step.

## Risks / Trade-offs

- **Alias rollover changes model behavior and price without a code deployment** → Persist the concrete model and methodology version; permit an environment override for rollback.
- **Prior score anchors the next opinion** → Send only compact context and explicitly require independent reassessment and evidence-based movement.
- **A failed model request creates a missing day** → Retry the same alias; prefer an honest gap over silently changing analysts.
- **The richer record grows the Git-backed JSON faster** → Keep thesis and factor lists concise and avoid copying article bodies into history; defer storage partitioning until size warrants it.
- **Confidence remains model opinion** → Display data quality separately so confidence is not mistaken for pipeline completeness.
- **Mixed legacy and v2 records complicate rendering** → Use explicit schema detection and retain existing field fallbacks.
- **OpenRouter `latest` means newest eligible, not independently benchmarked best** → Document this contract and log the resolved model rather than claiming an objective capability ranking.

## Migration Plan

1. Add contract tests and fixtures for valid, invalid, baseline, prior-context, retry, and corrupt-history cases.
2. Introduce v2 prompt generation, validation, model retry, derived fields, and atomic persistence behind the new methodology version.
3. Update the dashboard to render v2 records and preserve legacy rendering.
4. Update documentation to describe the editorial score, time horizon, alias behavior, and methodology boundary.
5. Run locally against fixtures and, if an API key is available, perform one non-persisting live OpenRouter verification.
6. Deploy through the existing workflow. The first successful run appends the first v2 entry; no prior records are modified.

Rollback consists of reverting the implementation commit. Existing v2 records remain valid JSON and contain the legacy-compatible score, status, reasoning, metrics, and date fields, so the prior dashboard can still render its core view.

## Open Questions

- What article age should define `fresh_articles`: 24 hours, 36 hours, or 48 hours, given daily scheduling delays and publisher timestamp variation? The implementation should choose and document a conservative default if not resolved.
- Should an alias rollover receive a visible chart annotation immediately, or is displaying model metadata on the latest opinion sufficient for the first iteration?
