## ADDED Requirements

### Requirement: Version-aware opinion rendering
The static dashboard SHALL detect version-2 opinions and render their structured fields while continuing to render legacy entries that do not declare a schema version.

#### Scenario: Latest record is version 2
- **WHEN** the latest history record declares schema version 2
- **THEN** the dashboard displays its score-derived status, thesis, detailed reasoning, confidence, factors, change information, data quality, and provenance

#### Scenario: Latest record is legacy
- **WHEN** the latest history record has no schema version
- **THEN** the dashboard retains the existing score, status, reasoning, metrics, and trend presentation and identifies unavailable enhanced metadata as legacy or unavailable

### Requirement: Opinion transparency
For a version-2 entry, the dashboard SHALL display the analysis timestamp, confidence, previous-score delta when available, model-authored change explanation, and requested and resolved model identifiers without presenting confidence as data completeness.

#### Scenario: Opinion has prior context
- **WHEN** the latest opinion contains a previous score and delta
- **THEN** the dashboard displays the signed score movement and its explanation

#### Scenario: Baseline opinion has no prior context
- **WHEN** the latest opinion is a baseline without a previous score
- **THEN** the dashboard labels it as a baseline and does not display a fabricated zero delta

### Requirement: Evidence balance display
The dashboard SHALL distinguish risk factors from stabilizing factors and SHALL display data-quality state and observed collection counts for version-2 opinions.

#### Scenario: Degraded evidence packet
- **WHEN** the latest opinion's data quality is degraded
- **THEN** the dashboard visibly marks the evidence as degraded while continuing to show the model's separate confidence and risk opinion

### Requirement: Freshness visibility
The dashboard SHALL show when the latest analysis was generated and SHALL visibly warn when its timestamp exceeds the documented freshness threshold.

#### Scenario: Current opinion
- **WHEN** the latest opinion is within the freshness threshold
- **THEN** the dashboard displays its update time without a stale warning

#### Scenario: Stale opinion
- **WHEN** the latest opinion is older than the freshness threshold
- **THEN** the dashboard displays a stale-data warning and does not imply that the old status is a current observation

### Requirement: Safe text rendering
The dashboard SHALL render all external, model-authored, and persisted string values through text-safe DOM operations rather than interpreting them as HTML.

#### Scenario: Headline contains markup
- **WHEN** a stored headline or factor contains HTML-like markup or a script payload
- **THEN** the dashboard displays it as literal text and does not execute or insert markup

### Requirement: Continuous mixed-version trend
The trend chart SHALL plot valid numeric scores from both legacy and version-2 entries in chronological history order and SHALL continue to limit the visible series to the most recent 30 valid points.

#### Scenario: History contains mixed schemas
- **WHEN** legacy and version-2 entries both contain valid numeric scores
- **THEN** the chart includes both kinds without requiring history migration
