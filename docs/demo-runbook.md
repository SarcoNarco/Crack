# Crack MVP demo runbook

This is a 3–5 minute recording run against the developer-owned, synthetic local demo only. It never authorizes testing public, third-party, or production systems.

## Prerequisites

Use Python dependencies already required by the repository and keep keys only in the ignored `agents/router/.env`. Load them into your shell without displaying values, then confirm only the variable *names* are set:

```sh
set -a
source agents/router/.env
set +a
[[ -n "${GROQ_API_KEY:-}" && -n "${GEMINI_API_KEY:-}" ]] && echo "Groq and Gemini key names present"
```

Start the disposable app (and coordinator, if you also want its health endpoint) using the operator command:

```sh
docker compose up --build -d
docker compose ps
```

## Recording flow

Run the one canonical workflow from the repository root:

```sh
python -m coordinator.demo
```

Point out the printed stage flow: fixed loopback preflight, source-only mapping, clean seeded reset, bounded identity discovery, two independent Groq/Gemini verifier attempts, code-owned verdict, exact run view, and deterministic Markdown/HTML generation. The final line names the exact verifier run and finding; the session manifest at `demo/output/<session-id>/manifest.json` records safe IDs and artifact paths.

Open the generated HTML manually in a browser using the printed path. Do not claim a recording exists unless you created and inspected a recording file.

The report and terminal view use the exact verifier run created by this invocation, not a latest-run lookup. A successful MVP run reports `DEMO VERIFIED`; `unverified`, `inconclusive`, and failed/incomplete results are honest non-success outcomes.

## Shutdown

```sh
docker compose down
```

## Troubleshooting

- Missing key name: load the ignored local `.env` again; never paste a key into chat or source control.
- Provider quota, retirement, or model failure: the demo stops; do not substitute providers or models.
- App-health failure: confirm Compose is running and its loopback port `8100` is available.
- `unverified` or `inconclusive`: preserve the report as a truthful result; it is not a completed verified demo.
- Report integrity failure: retain the manifest and investigate the new exact verifier run rather than using an older run.
