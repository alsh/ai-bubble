# Power Exponent Diagnostics

## Purpose

Provide reproducible, experimental measurements of daily-return scaling and extreme-return tail shape for instruments relevant to the AI investment boom.

## ADDED Requirements

### Requirement: Completed-session input provenance
The system SHALL use split- and dividend-adjusted daily closes for QQQ, SOXX, NVDA, and SPY. It SHALL identify the source, retrieval time, last input session, adjustment policy, and indicator version. It SHALL exclude future and incomplete-session prices.

#### Scenario: Manual run during trading
- **WHEN** a collection occurs before the current US regular session is complete
- **THEN** the current session's daily bar is excluded
- **AND** the data date identifies the last completed input session

#### Scenario: Corporate action
- **WHEN** a stock split or dividend occurs in the input history
- **THEN** returns use the consistently adjusted series rather than an artificial price jump

### Requirement: Causal and reproducible measurements
The system SHALL calculate DFA-1 on signed log returns and the Hill survival-tail exponent on absolute log returns. Every point SHALL use only prices through its labeled session. Published metadata SHALL identify the windows, scales, counts, and tail thresholds. Changes SHALL be measured in trading observations, not calendar days.

#### Scenario: Prefix invariance
- **WHEN** later prices are added to a fixed input series
- **THEN** measurements for an earlier session do not change

#### Scenario: Latest session is included
- **WHEN** there are exactly enough prices for a calculation
- **THEN** the first result is labeled with, and includes, the final input session

### Requirement: Explicit estimator limits
The system SHALL report DFA fit R² as descriptive fit quality, not as proof of long memory or trader synchronization. It SHALL show Hill tail-threshold sensitivity and sample counts. Insufficient, non-finite, constant, or otherwise degenerate inputs SHALL produce explicit unavailable measurements, not numeric sentinels or false normal states.

#### Scenario: All returns are zero
- **WHEN** a complete window contains constant prices
- **THEN** undefined exponents are null with an explanatory state
- **AND** the published artifact remains strict JSON

#### Scenario: No usable tail
- **WHEN** there are too few positive absolute returns or no positive log exceedances
- **THEN** the tail estimate is unavailable and its sample limitation is reported

### Requirement: Experimental separation from editorial opinion
The system SHALL label the indicators as experimental and not a crash forecast. It SHALL NOT derive a critical-state alert, crash probability, or editorial score adjustment from them. Existing LLM input and model-authored output contracts SHALL remain unchanged in this version.

#### Scenario: Large scaling exponent
- **WHEN** H exceeds 0.65 with a high fit R²
- **THEN** the dashboard displays the measurement without claiming a bubble or an imminent crash
- **AND** the value does not enter the LLM prompt or an automatic risk-score rule

### Requirement: Bounded independent indicator history
The system SHALL publish a bounded history of computed indicator points independently of editorial score records. It SHALL distinguish reconstructed historical diagnostics from measurements recorded by past runs. A feed failure SHALL be visible per instrument and SHALL NOT erase or relabel old data as current.

#### Scenario: Partial collection failure
- **WHEN** one instrument cannot be collected
- **THEN** the other instruments remain usable
- **AND** the failed instrument is marked unavailable or stale with its actual data date
- **AND** the editorial collection and opinion process can continue

#### Scenario: Reconstructed chart history
- **WHEN** past diagnostic points are calculated from a new historical-data retrieval
- **THEN** the artifact identifies them as reconstructed with the current retrieval time
- **AND** no past editorial record is created or changed

### Requirement: Separate exponent displays and history
The dashboard SHALL provide instrument selection, separate H and alpha history plots, H changes over one and five observations, descriptive H baseline deviation, fit R², sample counts, and data dates. Missing values SHALL remain chart gaps. The indicator panel SHALL be independent of the selected editorial-history record and shall state this separation.

#### Scenario: Legacy-only history
- **WHEN** the dashboard has old editorial records but no indicator artifact
- **THEN** the existing dashboard remains usable
- **AND** the indicator panel states that diagnostic data is unavailable

#### Scenario: Instrument and date inspection
- **WHEN** the user changes instruments or inspects a diagnostic history point
- **THEN** the charts identify the instrument, session, exponent, and relevant sample information
- **AND** the editorial risk-score history is not replaced or rescaled

### Requirement: Safe publication and daily operation
Indicator publication SHALL use strict JSON and atomic file replacement. A failed replacement SHALL preserve the previous artifact. Scheduled runs SHALL occur after the US regular market close in both standard and daylight-saving time. Raw fetched price histories SHALL NOT be added to the public artifact by this change.

#### Scenario: Write failure
- **WHEN** an indicator artifact replacement fails
- **THEN** the previous destination file remains unchanged
- **AND** temporary files are removed

#### Scenario: Daily schedule
- **WHEN** the daily workflow starts at its scheduled UTC time
- **THEN** the US regular session has ended in either seasonal time offset
