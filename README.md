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

## Evidence reports

Generate deterministic Markdown and standalone HTML reports together from a completed verifier run:

```sh
python -m reports.generate --latest
python -m reports.generate --run-id <verifier_run_id>
```

`--latest` selects the most recently inserted completed verifier run; an explicit run ID must also be a completed verifier run. Reports are written only to `reports/output/`, which is ignored by Git. Generation opens the fixed repository-local ledger in SQLite read-only mode: it never reruns agents, resets the demo app, or writes ledger rows, findings, or verification statuses. The HTML output is a standalone semantic document with static styling and no JavaScript.
