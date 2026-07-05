# ADR-0002: LLM verdict contract

## Status

Accepted

## Context

The project uses a deterministic tender scoring pipeline.
The LLM layer is planned as an auxiliary classifier for narrow evidence-based tasks.
Before implementing the LLM client, the project must define where LLM output is stored and how it interacts with deterministic rules.

## Decision

LLM output must be stored as advisory metadata inside each rule:

rule["llm_verdict"]

The LLM verdict must not overwrite deterministic fields:
- rule["status"]
- rule["risk"]
- rule["human_review_required"]
- rule["comment"]
- scenario_result

The scenario classifier must not read rule["llm_verdict"] unless a separate future ADR explicitly changes this decision.

## Contract

Persisted LLM metadata must be nested under rule["llm_verdict"].

Required fields when LLM was attempted:

- invocation_status: "ok" | "skipped" | "unavailable" | "invalid_json" | "error"
- rule_id: string
- verdict: "pass" | "fail" | "unknown" | "conflict"
- confidence: "high" | "medium" | "low"
- human_review_required: boolean
- reason: string
- supporting_evidence_ids: array of integers
- warnings: array of strings
- conflicts_with_rule: boolean
- deterministic_status: "pass" | "fail" | "unknown" | "conflict"
- provider: string
- model: string

Optional fields:
- error_type
- error_message
- raw_response_saved

## Confidence naming

The field name confidence is allowed only inside rule["llm_verdict"].

It must not be confused with scenario_result["confidence"], which represents confidence of the final deterministic scenario.

## Conflict handling

If deterministic rule status and LLM verdict disagree, the deterministic rule remains unchanged.

The conflict must be recorded only as diagnostic metadata:
- rule["llm_verdict"]["conflicts_with_rule"] = true
- rule["llm_verdict"]["warnings"] must include a short conflict description

The conflict must not change scenario_result in MVP.

## Failure handling

If Ollama is unavailable, the model times out, or JSON is invalid:
- deterministic pipeline must continue;
- rule fields must remain unchanged;
- rule["llm_verdict"]["invocation_status"] must describe the failure;
- warnings must explain the failure.

## Consequences

- LLM integration can be added safely in shadow mode.
- Existing deterministic outputs remain authoritative.
- scenario_classifier remains isolated from LLM metadata.
- Future code can compare rule verdict and LLM verdict without changing business logic.
