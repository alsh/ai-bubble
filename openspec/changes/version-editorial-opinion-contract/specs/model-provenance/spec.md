## ADDED Requirements

### Requirement: Current OpenAI GPT alias by default
The agent SHALL request `~openai/gpt-latest` by default for daily opinions. A documented environment configuration MAY override the requested model for testing or controlled rollback without changing source code.

#### Scenario: Default production request
- **WHEN** no model override is configured
- **THEN** the OpenRouter request uses `~openai/gpt-latest`

#### Scenario: Controlled override
- **WHEN** a model override is configured
- **THEN** the OpenRouter request uses that exact configured slug and records it as the requested model

### Requirement: Resolved model provenance
Each successful version-2 opinion SHALL persist both the requested model slug and the concrete model identifier reported by OpenRouter's completion response.

#### Scenario: Alias resolves successfully
- **WHEN** `~openai/gpt-latest` is requested and OpenRouter reports a concrete OpenAI model in the response
- **THEN** the opinion records the alias as requested and the reported concrete identifier as resolved

#### Scenario: Resolved identity is unavailable
- **WHEN** a successful-looking response does not provide a non-empty resolved model identifier
- **THEN** the response fails validation and no opinion is appended

### Requirement: Stable-vendor retry behavior
The agent SHALL use bounded retries of the same requested model for transient failures and SHALL NOT silently substitute a model from another vendor or family.

#### Scenario: Transient request failure
- **WHEN** the first request to the requested model fails transiently and a bounded retry succeeds
- **THEN** the successful opinion is persisted with the same requested model identity

#### Scenario: Retry budget exhausted
- **WHEN** all bounded attempts to the requested model fail
- **THEN** the run exits with failure and history remains unchanged

### Requirement: Methodology provenance
Each version-2 opinion SHALL record `canary-opinion-v2` as its methodology version independently of the concrete model identifier.

#### Scenario: OpenRouter advances the alias
- **WHEN** two daily runs resolve the same requested alias to different concrete models
- **THEN** each record retains its own resolved model while both retain the applicable methodology version
