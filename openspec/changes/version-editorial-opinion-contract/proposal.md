## Why

The Canary intentionally publishes a model-authored opinion, but its current prompt frames that opinion as fixed arithmetic while allowing unstructured discretion, producing contradictory scores, statuses, and explanations. The project needs a stable, transparent editorial contract and automatic use of OpenRouter's current OpenAI GPT flagship without adding operational infrastructure.

## What Changes

- Define the score as the model's opinion of how fragile the AI investment boom is to a meaningful correction within the next 6–12 months.
- Introduce a versioned, structured daily opinion containing a score, confidence, thesis, risk factors, stabilizing factors, change explanation, data quality, and model/methodology provenance.
- Preserve model discretion over the score while deriving the display status deterministically from that score.
- Give each analysis compact historical context so the model can explain material day-to-day changes without receiving the full archive.
- Request `~openai/gpt-latest` by default and record the concrete model returned by OpenRouter.
- Replace silent cross-vendor model substitution with retries of the default alias and an explicit failed run if the alias remains unavailable.
- Validate the opinion contract before persistence and expose freshness, confidence, provenance, and score-change context on the existing static dashboard.
- Preserve the existing single GitHub Action, Python process, JSON-backed Git history, and GitHub Pages deployment model.

## Capabilities

### New Capabilities
- `editorial-opinion`: Defines the meaning, structured output, validation, historical context, status derivation, and persistence behavior of a daily Canary opinion.
- `model-provenance`: Defines default OpenRouter model selection and recording of requested and resolved model identity and methodology version.
- `opinion-dashboard`: Defines presentation of the opinion, confidence, freshness, score movement, and provenance in the static dashboard.

### Modified Capabilities

None. No existing OpenSpec capabilities are defined.

## Impact

- `src/agent.py`: prompt, model selection, response validation, compact history context, status derivation, and persisted schema.
- `data/status_history.json`: new entries gain a versioned schema; existing entries remain readable and are not rewritten.
- `index.html`: render the richer opinion contract while remaining compatible with legacy history entries.
- `tests/`: add contract, failure-path, provenance, and dashboard-facing data tests.
- `.github/workflows/daily.yml`: retain the current deployment topology; only execution safeguards such as retry/failure behavior may change.
- OpenRouter usage may track flagship-model pricing and behavior as the `~openai/gpt-latest` alias advances.
