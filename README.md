# Prompt Library

A version-controlled, schema-validated, testable library of production prompts.

Prompts here are treated as **code**: each one has an owner, a semantic version, declared
inputs, an output contract, a changelog, and (once stable) an eval suite that runs in CI.

```
prompts/
  <domain>/
    <prompt-name>/
      prompt.yaml     # metadata + template (required)
      evals.yaml      # test cases + assertions (required when status: stable)
      README.md       # optional: usage notes, examples, known limits
schema/               # JSON Schemas for prompt.yaml and evals.yaml
templates/            # starter files for new prompts
tools/promptctl.py    # CLI: list / validate / render / eval / catalog
tests/                # unit tests for the tooling itself
CATALOG.md            # generated index of every prompt
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make validate                       # schema + lint every prompt
make eval                           # offline: every eval case renders
ANTHROPIC_API_KEY=sk-... make eval-live   # live: call the model, run assertions

python tools/promptctl.py list
python tools/promptctl.py render engineering.code-review \
  -v language="C# .NET 8" -v code=@src/Handler.cs
python tools/promptctl.py render engineering.code-review --vars-file vars.yaml --json
```

`render --json` emits a Messages-API-shaped body you can pipe straight into `curl` or an SDK.

## Prompt anatomy

```yaml
id: observability.trace-triage     # must equal the folder path, dotted
name: Distributed Trace Triage
version: 1.0.0                     # SemVer — see below
description: What it does, in one or two sentences.
owner: "@github-handle"
status: draft | experimental | stable | deprecated
tags: [opentelemetry, incident-response]
model: { provider: anthropic, name: claude-sonnet-5, temperature: 0, max_tokens: 3000 }
variables:
  - name: trace
    description: The trace export.
  - name: architecture_notes
    description: Optional context.
    required: false
    default: "None provided."
template:
  system: |
    Role, rules, and the reasoning behind them.
  user: |
    Symptom: {{symptom}}
    <trace>{{trace}}</trace>
output: { format: markdown }       # or json + json_schema
changelog:
  - { version: 1.0.0, date: 2026-09-25, notes: Initial release. }
```

Variables use `{{name}}` placeholders. The linter fails the build if a template references an
undeclared variable, and warns when a declared variable is never used.

## Versioning

| Change | Bump |
|---|---|
| Add/remove/rename a variable, change output format or JSON contract | **MAJOR** |
| Change instructions in a way that changes behaviour | **MINOR** |
| Typo, wording clarification, no behavioural change | **PATCH** |

The newest `changelog` entry must match `version` — CI enforces this.

## Lifecycle

`draft` → `experimental` (has evals, in trial use) → `stable` (evals required, passes live
evals) → `deprecated` (kept for consumers pinned to it; add a note pointing to the replacement).

## Evals

`evals.yaml` holds cases, each with input `vars` and a list of assertions:

| Assertion | Passes when |
|---|---|
| `contains` / `not_contains` | substring present / absent (case-insensitive by default) |
| `regex` | pattern matches |
| `is_json` | output (or its fenced block) parses as JSON |
| `json_schema` | parsed JSON validates against the given schema |
| `max_chars` | output length ≤ value |

Offline mode (default, runs on every PR) proves every case renders with the declared
variables. Live mode (`--live`) calls the model at the prompt's configured settings and runs
the assertions; CI runs it on `main` and on demand when the `ANTHROPIC_API_KEY` secret is set.
Set `PROMPTCTL_MODEL_OVERRIDE` to evaluate a prompt against a different model.

## Catalog

See [CATALOG.md](CATALOG.md), regenerated with `make catalog`. CI fails if it is out of date.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
