## ADDED Requirements

### Requirement: Stable editorial question
The system SHALL ask the model to provide an editorial opinion of how fragile the AI investment boom is to a meaningful correction within the next 6–12 months. The prompt SHALL present valuation, investment efficiency and financing, adoption, hardware demand, concentration, price behavior, and stabilizing evidence as analytical lenses rather than fixed additive rules.

#### Scenario: Model evaluates competing evidence
- **WHEN** the evidence contains both elevated financing risk and strong revenue growth
- **THEN** the model is permitted to weigh those factors holistically and SHALL explain how they support its score

### Requirement: Versioned structured opinion
Each newly persisted opinion SHALL use schema version 2 and methodology version `canary-opinion-v2` and SHALL contain a model-authored score, confidence, thesis, reasoning, risk factors, stabilizing factors, and change explanation together with application-authored metadata.

#### Scenario: Complete opinion is returned
- **WHEN** the model returns all required opinion fields in their valid domains
- **THEN** the system persists them in a version-2 record with the methodology version

#### Scenario: Opinion violates the contract
- **WHEN** the model response is malformed, omits a required field, uses an invalid field type, or provides a score outside 0 through 100
- **THEN** the system SHALL fail the run without appending an entry

### Requirement: Model-owned score and derived status
The model SHALL own the numeric risk opinion. The application SHALL derive status from the validated score as `GREEN` for 0–30, `YELLOW` for 31–69, and `RED` for 70–100, and the model SHALL NOT independently supply persisted status.

#### Scenario: High-risk opinion
- **WHEN** the validated model score is 74
- **THEN** the persisted status is `RED`

#### Scenario: Boundary opinions
- **WHEN** validated scores are 30, 31, 69, and 70
- **THEN** their statuses are `GREEN`, `YELLOW`, `YELLOW`, and `RED` respectively

### Requirement: Compact historical context
The system SHALL provide the model with the previous valid opinion's score and thesis and at most seven recent valid scores. The prompt SHALL require independent reassessment and an explanation of material score movement.

#### Scenario: Prior opinion exists
- **WHEN** at least one historical record contains a valid numeric score
- **THEN** the next prompt includes the latest valid score and thesis plus no more than seven recent scores

#### Scenario: Baseline opinion
- **WHEN** no prior valid opinion exists
- **THEN** the prompt identifies the analysis as a baseline and the persisted change metadata SHALL not fabricate a previous score or delta

### Requirement: Application-owned change arithmetic
The system SHALL compute the prior score and numeric delta from persisted history and the current validated score while preserving the model's explanation for the movement.

#### Scenario: Score increases
- **WHEN** the previous valid score is 45 and the current model score is 52
- **THEN** the persisted change metadata records previous score 45 and delta 7

### Requirement: Independent data-quality metadata
The system SHALL compute and persist data-quality metadata from observable collection results, including market-data completeness, fetched article count, and fresh article count. Data quality SHALL remain separate from the model's confidence and risk score.

#### Scenario: Partial news evidence
- **WHEN** market data is complete but fewer than the expected number of fresh articles are collected
- **THEN** the run may publish an opinion but SHALL mark the saved data quality as degraded and report the observed counts

#### Scenario: Evidence packet is empty
- **WHEN** neither usable market data nor usable news evidence is available
- **THEN** the system SHALL fail without publishing an opinion

### Requirement: Safe history persistence
The system SHALL require existing history to be a valid JSON array and SHALL update it atomically so failed parsing, validation, or writing cannot replace valid history with a partial or reset file.

#### Scenario: Existing history is corrupt
- **WHEN** the history file cannot be parsed as a JSON array
- **THEN** the run fails and leaves the file unchanged

#### Scenario: Atomic replacement fails
- **WHEN** writing or replacing the updated history fails
- **THEN** the original history remains available and no partial destination file is published

### Requirement: Legacy history preservation
The system SHALL append version-2 entries without modifying or re-scoring legacy records and SHALL retain the legacy-compatible `date`, `score`, `status`, `reasoning`, and `metrics` fields in new entries.

#### Scenario: First version-2 append
- **WHEN** legacy entries already exist and a valid version-2 opinion is saved
- **THEN** all legacy entries remain byte-equivalent in parsed value and the new opinion is appended after them
