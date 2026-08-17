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
