# Proposal

## Why

The Canary has an editorial risk score, but it has no reproducible measure of return scaling or extreme-return tail shape. Add these measurements as experimental diagnostics, without treating them as proof of a bubble or as a crash forecast.

## What Changes

- Add a versioned deterministic DFA-1 scaling exponent and Hill tail exponent calculation, with separate sampling windows, input checks, and explicit missing-data states.
- Use completed-session, split- and dividend-adjusted daily closes for QQQ, SOXX, NVDA, and SPY. Show each instrument separately; do not pool their returns or claim that they measure the whole AI economy.
- Add a Power exponents dashboard panel with H and alpha history graphs, session-to-session H changes, fit R², data dates, sample sizes, and tail-threshold sensitivity.
- Store a bounded indicator-history artifact independently of the editorial score history. Preserve existing records and schema compatibility.
- Keep the experimental indicators out of the LLM prompt and risk-score rules in this version. Do not issue a critical-state or crash alert.
- Run the daily workflow after the US market close in both daylight-saving and standard time. Reject incomplete daily bars during manual runs.
- Document statistical limits, data provenance, data-use restrictions, and the separate validation required before predictive use.

## Capabilities

### New Capabilities

- `power-exponent-diagnostics`: Collect suitable completed-session returns, calculate and publish experimental scaling and tail diagnostics, and display their time evolution without changing the editorial risk score.

### Modified Capabilities

None. No main capability specifications exist in this repository.

## Impact

- New calculation/collection module and deterministic tests.
- Small integration in `src/agent.py`; additive application-owned metadata only.
- `index.html` gains an independent indicator panel and Chart.js plots.
- `requirements.txt` explicitly declares NumPy; pandas and yfinance are already used.
- A bounded `data/power_exponents.json` artifact is produced by the scheduled run. Raw price history is not published by this change.
- `.github/workflows/daily.yml`, `README.md`, and a methodology document are updated.
- No new service, database, model request, paid data subscription, automatic deployment, or change to existing OpenSpec work is required.
