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

### Sprint 1 addendum

Added authenticated `GET /records/mine`, registered before the parameterized record route, so a normal in-app Account B flow can return only Account B's own record IDs and fields. This narrowly supports the contained authorization test without exposing fixture files, database access, or new write behavior.

### Sprint 2

Built the five-function scope-controller gateway with resolved source-path containment, fixed loopback HTTP access and seeded-token/method allowlists, a fixed-path Sprint 1 reset, and ledger-owned event recording. No host, token, database, environment, filesystem, or shell scope is configurable; assumption: the fixed app origin is `http://127.0.0.1:8100`, and the specified endpoint API intentionally sends no request body.

### Sprint 3

Built the config-driven model router under `agents/router/`, with committed provider base URLs and role-to-model mappings, environment-only provider credentials, and a thin OpenAI-compatible completion wrapper for both Groq and OpenAI. Every successful completion records metadata-only evidence through the scope controller, excluding prompts, responses, and API keys. Assumption: both providers use the OpenAI SDK Chat Completions interface; the scope controller supplies the evidence timestamp.

### Sprint 4

Built the source-only mapper agent under `agents/mapper/`, with a Pydantic-validated app-contract schema, exactly one stricter retry for malformed model output, run/event ledger records, and a development-facing `output/app_contract.json` artifact. The mapper reads only a fixed source allowlist through `scope_controller.read_source`; the scope controller now explicitly blocks `app-under-test/README.md` for every agent, and the mapper makes no live app requests. Assumptions: the fixed Sprint 1 source paths are the complete mapper input for this pass, seeded account identifiers are usable inferred role names, and a single fenced JSON document can be unwrapped before Pydantic validation while any other malformed response fails loudly.

### Sprint 5

Extended the existing ledger persistence boundary and scope controller with `submit_hypothesis`, append-only `update_verification_status`, and verified-only `record_finding` public capabilities. Hypothesis status changes copy the latest revision into a new row and write an audit event; submissions and findings also write audit events. Added tests for submission, unverified-finding rejection, append-only status history, verified finding creation, allowed statuses, and the absence of generic hypothesis update/delete paths. Assumption: because `record_finding` has no run-ID argument, its audit event uses the latest verifier run ID, falling back to the submitting run only when no verifier ID exists.

### Sprint 6

Built the bounded identity/authorization agent under `agents/identity/`. It reads the Sprint 4 app contract directly, uses the `identity` model-router role to select the declared read route and phrase only unverified hypotheses, then makes exactly two normal-flow scope-controller calls: Account B `GET /records/mine`, followed by Account A `GET /records/{record_id}` using the discovered ID. It records each result via `record_evidence` and submits through `submit_hypothesis` only after Account A receives an Account B-owned record. The CLI is `python -m agents.identity.run`; tests cover no finding, a cross-account read hypothesis, and the two-call bound with no login or write call. Assumption: `owner_account_id` is the app's ownership field, based on the normal response shape; the agent does not read source, the database, or `app-under-test/README.md`. Groq retired `qwen/qwen3-32b`; the identity router now uses the lower-output-cost replacement `openai/gpt-oss-120b` with low reasoning effort. The live acceptance pass succeeded: Account B discovered `note-account-b-001`, Account A retrieved it through the missing `GET /records/{record_id}` ownership boundary, and the agent submitted an unverified hypothesis. This successful structured-output and reproduction pass accepts GPT-OSS for this role.

### Sprint 8

Built the independent verifier under `agents/verifier/`. For an unverified hypothesis read only through the scope controller's fixed-ledger `read_hypothesis` capability, verifier_a and verifier_b independently receive only the same concise claim and expected evidence and each propose a Pydantic-validated, GET-only reproduction plan. The verifier resets the disposable app before each attempt, producing a distinct reset UUID plus a logical hash of the identical ordered seeded account and record rows, executes each plan only through `call_app_endpoint`, and records metadata-only evidence for every reset, validated plan, call, deterministic check, and verdict. Ordinary code applies the same sequential success predicate to both attempts: a successful Account B response must first discover a valid Account B-owned record ID, then a later successful Account A response must return that exact ID with its owner still normalized specifically to Account B. Two successes produce `verified`, two failures produce `unverified`, and disagreement produces `inconclusive`; only `verified` immediately calls the existing verified-only `record_finding` capability. A provider failure, malformed output, quota error, or otherwise incomplete attempt fails closed without a verdict or finding. The CLI is `python -m agents.verifier.run <hypothesis_id>`, and mocked tests cover the exact-record predicate, every verdict, verified-only finding creation, provider and malformed-output failures, and two independent clean resets. Assumptions: verifier plans are limited to at most five `GET` calls against `/records/mine`, `/records/{record_id}`, or one safe concrete record path; an unresolved record-ID placeholder is not executed. During this sprint Groq retired Kimi K2 from its available catalog, so verifier_a deliberately uses `openai/gpt-oss-120b` on Groq with low reasoning effort, the same model currently used by the Sprint 6 identity agent. The original OpenAI verifier_b run then failed for insufficient paid API quota, so verifier_b was moved narrowly to Google's OpenAI-compatible endpoint using `gemini-3.5-flash` and `GEMINI_API_KEY`; generic OpenAI provider support remains available but is no longer active for verification. The planners remain independent despite the provider change: verifier_a uses Groq and verifier_b uses Gemini, each receives an isolated copy of only the concise claim and expected evidence, neither sees the other's plan or result, and each starts after a separate clean reset. The free-tier privacy tradeoff is explicit: only concise synthetic lab claims and expected evidence may be sent to Gemini; real credentials, secrets, third-party data, prompts beyond that bounded input, and private application data are prohibited, and the Gemini free tier is not represented as private processing. The five-suite regression passes 60 tests. A live Gemini JSON-mode compatibility probe produced a valid Pydantic plan, and the live Groq/Gemini acceptance run `verifier:c747fe6f-e45c-487c-a681-76df255b0181` completed against the loopback demo app. Verifier_a and verifier_b used distinct reset UUIDs with the identical logical state hash `1bc3c2fa4a64fea8`, each proposed two bounded GET calls, and each independently reproduced Account A reading Account B record `note-account-b-001`; the code-owned checks both succeeded. Hypothesis `6536e9e5-fe1f-42c3-90f4-a11cc963a405` received an append-only `verified` revision, and verified-only finding `18d833c2-d172-4d8f-8820-288527184751` was recorded with remediation to enforce server-side ownership before returning a record.

### Sprint 9

Added `python -m ui.run_view --latest` and `--run-id <run_id>`, a deterministic terminal view over a ledger-owned SQLite read boundary. It displays run metadata, ordered events, latest append-only hypothesis revisions, and linked findings without invoking agents, providers, the demo app, or ledger writes. Assumption: the production view uses the fixed `data/ledger.db`; tests may inject temporary database paths.

## Known follow-ups

- Repo-wide pytest collection still collides because mapper, identity, and verifier each have an un-packaged `test_agent.py`; run these suites individually until that layout is corrected in a future sprint.
