"""Deterministic, read-only terminal view of one Crack ledger run."""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

from ledger.read_view import LedgerReadError, RunView, read_latest_run, read_run


_ANSI = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|$)|\[[0-?]*[ -/]*[@-~]|[@-_])")
_DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "data" / "ledger.db"


def safe_text(value: object, limit: int = 180) -> str:
    """Render untrusted ledger text as one bounded terminal-safe line."""
    text = _ANSI.sub("[control]", "" if value is None else str(value))
    rendered: list[str] = []
    for character in text:
        code = ord(character)
        if character == "\n":
            rendered.append("\\n")
        elif character == "\r":
            rendered.append("\\r")
        elif code < 32 or code == 127 or unicodedata.category(character) in {"Cc", "Cf"}:
            rendered.append(f"\\x{code:02x}")
        else:
            rendered.append(character)
    text = "".join(rendered)
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def format_run(view: RunView) -> str:
    run = view.run
    lines = [
        "CRACK RUN VIEW (read-only)", f"Run ID: {safe_text(run.id)}",
        f"Agent role: {safe_text(run.agent_role)}", f"Status: {safe_text(run.status)}",
        f"Application version: {safe_text(run.app_version)}",
        f"Environment snapshot ID: {safe_text(run.environment_snapshot_id)}",
        f"Declared scope: {safe_text(run.declared_scope)}", f"Start: {safe_text(run.start_time)}",
        f"End: {safe_text(run.end_time)}", f"Budgets: {run.token_budget} tokens, {run.time_budget} seconds",
        "", "EVENTS",
    ]
    if not view.events:
        lines.append("No events recorded for this run.")
    else:
        for event in view.events:
            lines.extend([
                f"[{event.sequence_number}] {safe_text(event.action_type)} ({safe_text(event.policy_decision)}) {safe_text(event.timestamp)}",
                f"    Summary: {safe_text(event.request_response_summary)}",
                f"    Artifact: {safe_text(event.artifact_reference)}",
            ])
    lines.extend(["", "HYPOTHESES"])
    if not view.hypotheses:
        lines.append("No hypotheses associated with this run.")
    else:
        for hypothesis in view.hypotheses:
            verifier = "none" if hypothesis.verifier_run_id is None else hypothesis.verifier_run_id
            lines.extend([
                f"- Hypothesis ID: {safe_text(hypothesis.id)}", f"  Claim: {safe_text(hypothesis.concise_claim)}",
                f"  Affected rule: {safe_text(hypothesis.affected_app_rule)}",
                f"  Verification: {safe_text(hypothesis.verification_status)}",
                f"  Submitting run: {safe_text(hypothesis.submitted_by_run)}", f"  Verifier run: {safe_text(verifier)}",
            ])
    lines.extend(["", "FINDINGS"])
    if not view.findings:
        lines.append("No findings linked to this run's hypotheses.")
    else:
        for finding in view.findings:
            lines.extend([
                f"- Finding ID: {safe_text(finding.id)}", f"  Hypothesis: {safe_text(finding.hypothesis_id)}",
                f"  Severity rationale: {safe_text(finding.severity_rationale)}",
                f"  Remediation: {safe_text(finding.remediation_direction)}",
                f"  Evidence references: {safe_text(finding.evidence_references)}",
            ])
    return "\n".join(lines) + "\n"


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(f"invalid arguments: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="python -m ui.run_view", add_help=True)
    selectors = parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--latest", action="store_true", help="show the latest run")
    selectors.add_argument("--run-id", help="show one exact run ID")
    return parser


def main(argv: list[str] | None = None, *, database_path: str | Path = _DEFAULT_DATABASE) -> int:
    try:
        args = _parser().parse_args(argv)
        view = read_latest_run(database_path) if args.latest else read_run(args.run_id, database_path)
        sys.stdout.write(format_run(view))
        return 0
    except (LedgerReadError, ValueError) as exc:
        sys.stderr.write(f"run view error: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
