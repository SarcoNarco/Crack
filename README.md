# Crack

Sprint 0 scaffold for Crack, a local-first contained security lab. This sprint includes a health-only FastAPI coordinator and a raw SQLite ledger schema.

See [AGENTS.md](AGENTS.md) for the authoritative project context, security rules, layout, assumptions, and sprint history.

## Read-only run view

Inspect the latest ledger run or one exact run from the terminal:

```sh
python -m ui.run_view --latest
python -m ui.run_view --run-id <run_id>
```

The view displays run metadata, ordered evidence events, latest append-only hypothesis revisions, and linked findings. It opens the fixed repository-local ledger in SQLite read-only mode and never starts agents or writes ledger data.

## Canonical MVP demo

With the existing local Groq and Gemini environment variables loaded (without printing their values) and the local Compose services running, execute:

```sh
python -m coordinator.demo
```

The fail-closed workflow checks the fixed loopback app and four configured roles, maps source through the scope controller, resets the disposable app, runs identity, passes its exact single hypothesis to the independent verifier, then uses that exact verifier run for the terminal view and twice-generated deterministic reports. It prints safe IDs and artifact paths and writes an ignored session manifest under `demo/output/`.

Exit code `0` means one new hypothesis was independently reproduced as `verified` with a real finding and byte-stable Markdown and HTML reports. `unverified`, `inconclusive`, provider, app, schema, or integrity failures are not presented as demo success. See [the recording runbook](docs/demo-runbook.md) for prerequisites, presentation flow, shutdown, and troubleshooting.

## Evidence reports

Generate deterministic Markdown and standalone HTML reports together from a completed verifier run:

```sh
python -m reports.generate --latest
python -m reports.generate --run-id <verifier_run_id>
```

`--latest` selects the most recently inserted completed verifier run; an explicit run ID must also be a completed verifier run. Reports are written only to `reports/output/`, which is ignored by Git. Generation opens the fixed repository-local ledger in SQLite read-only mode: it never reruns agents, resets the demo app, or writes ledger rows, findings, or verification statuses. The HTML output is a standalone semantic document with static styling and no JavaScript.
