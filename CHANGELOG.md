# Changelog

Repository-level changes (tooling, schema, CI). Per-prompt history lives in each
`prompt.yaml` under `changelog`.

## [0.1.0] - 2026-09-25

### Added
- Prompt and eval JSON Schemas.
- `promptctl` CLI: list, validate (schema + lint), render, eval (offline/live), catalog.
- CI: unit tests, validation, offline evals, catalog freshness; live evals on `main`.
- Starter prompts: BizTalk orchestration analysis, OTel trace triage, code review,
  ADR writer, agent system-prompt architect.
