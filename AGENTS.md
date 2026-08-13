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

### Sprint 2

Built the five-function scope-controller gateway with resolved source-path containment, fixed loopback HTTP access and seeded-token/method allowlists, a fixed-path Sprint 1 reset, and ledger-owned event recording. No host, token, database, environment, filesystem, or shell scope is configurable; assumption: the fixed app origin is `http://127.0.0.1:8100`, and the specified endpoint API intentionally sends no request body.

### Sprint 3

Built the config-driven model router under `agents/router/`, with committed provider base URLs and role-to-model mappings, environment-only provider credentials, and a thin OpenAI-compatible completion wrapper for both Groq and OpenAI. Every successful completion records metadata-only evidence through the scope controller, excluding prompts, responses, and API keys. Assumption: both providers use the OpenAI SDK Chat Completions interface; the scope controller supplies the evidence timestamp.

### Sprint 4

Built the source-only mapper agent under `agents/mapper/`, with a Pydantic-validated app-contract schema, exactly one stricter retry for malformed model output, run/event ledger records, and a development-facing `output/app_contract.json` artifact. The mapper reads only a fixed source allowlist through `scope_controller.read_source`; the scope controller now explicitly blocks `app-under-test/README.md` for every agent, and the mapper makes no live app requests. Assumptions: the fixed Sprint 1 source paths are the complete mapper input for this pass, seeded account identifiers are usable inferred role names, and a single fenced JSON document can be unwrapped before Pydantic validation while any other malformed response fails loudly.

### Sprint 5

Extended the existing ledger persistence boundary and scope controller with `submit_hypothesis`, append-only `update_verification_status`, and verified-only `record_finding` public capabilities. Hypothesis status changes copy the latest revision into a new row and write an audit event; submissions and findings also write audit events. Added tests for submission, unverified-finding rejection, append-only status history, verified finding creation, allowed statuses, and the absence of generic hypothesis update/delete paths. Assumption: because `record_finding` has no run-ID argument, its audit event uses the latest verifier run ID, falling back to the submitting run only when no verifier ID exists.
