# Contributing

## Adding a prompt

1. Copy the starter: `cp -r templates/prompt prompts/<domain>/<prompt-name>`
2. Set `id` to `<domain>.<prompt-name>` (lowercase, hyphens allowed in the name).
3. Write the template. Declare every `{{variable}}` under `variables`.
4. Add at least two eval cases: one happy path, one that probes a known failure mode.
5. Run `make check` (validate + offline evals + catalog + unit tests).
6. Open a PR using the template. Paste live-eval output if you ran it.

## Prompt-writing standards

- **Explain the why.** Rules with reasons generalise better than bare prohibitions.
- **Separate data from instructions** with XML tags (`<code>`, `<trace>`, `<notes>`).
- **Define the output contract explicitly** — headings, JSON keys, or a JSON schema.
- **Say what to do when information is missing** (list it as an open question; don't guess).
- **Keep the system prompt for durable behaviour**, the user template for the task.
- **No secrets, client names, or real customer data** in templates or eval fixtures.
  Use synthetic data; scrub anything derived from real incidents.
- Prefer `temperature: 0` for analysis/extraction prompts; raise it only for generative work.

## Changing a prompt

Bump `version` per the table in the README and add a `changelog` entry at the **top** of the
list. If a change is MAJOR, consider keeping the old version under a new id suffix
(e.g. `...-v1`, status `deprecated`) for pinned consumers.

## Review checklist

- [ ] Version bumped correctly and changelog updated
- [ ] Evals added/updated and passing offline
- [ ] Live evals run (for `stable` prompts) or explicitly noted as not run
- [ ] No sensitive data in templates or fixtures
- [ ] `CATALOG.md` regenerated
