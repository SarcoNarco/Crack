# Crack — Project Context

Crack is a local-first, contained, verification-first security lab for running bounded agents against a disposable, developer-owned demo app. It is never a general scanner and never touches third-party applications, live domains, or real credentials.

## Directory layout

- `app-under-test/` — Empty placeholder for the disposable demo app added in Sprint 1.
- `coordinator/` — Minimal FastAPI coordinator service for the local lab.
- `ledger/` — Raw SQLite schema and migration/init assets for the evidence ledger.
- `agents/` — Empty placeholder for later agent implementations.
- `scope-controller/` — Empty placeholder for the Sprint 2 scope controller.
- `ui/` — Empty placeholder for the later React and TypeScript interface.
- `docker-compose.yml` — Local Compose definition for the coordinator service only.

## Tech stack

- Python with FastAPI for the backend
- SQLite for the ledger
- Docker Compose for isolation
- React with TypeScript planned for a later sprint, not Sprint 0

## Security invariants

Agents must never get direct network, shell, or credential access. Those capabilities arrive in Sprint 2 through the scope controller and must be enforced in code, not by prompts.

## Sprint 0 assumptions

The coordinator and ledger use the repository-local path `./data/ledger.db`; the initialization script creates its parent directory and database file when needed. The four requested ledger tables use SQLite `TEXT` columns for identifiers, timestamps, statuses, summaries, references, and other unconstrained fields, with `INTEGER` for sequence and budget values.

The provided workspace had no Git metadata, so Sprint 0 initializes a local repository with `main` as the base branch and `sprint-0-scaffold` as the working branch.

## Sprint log

### Sprint 0

Scaffolded the local-only FastAPI coordinator with `GET /health`, the raw SQLite ledger schema and initializer, and a coordinator-only Docker Compose setup. Added empty future-sprint directories and documented the containment rules and assumptions.

### Sprint 1

Built the fixed, local-only FastAPI demo notes app with deterministic Account A/Account B fixtures, seed reset script, and Compose service on port 8100. The sole intentional flaw is a missing record-owner comparison on authenticated `GET /records/{id}`; write paths enforce ownership. Assumption: fixed bearer tokens and SQLite fixtures are adequate because authentication itself is out of Sprint 1 scope.
