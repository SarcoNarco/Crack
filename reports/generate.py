"""Generate deterministic Markdown and standalone HTML evidence reports."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ledger.read_view import Finding, Hypothesis, LedgerReadError, RunView, read_latest_verifier_run, read_run


_DEFAULT_DATABASE = Path(__file__).resolve().parents[1] / "data" / "ledger.db"
_DEFAULT_OUTPUT = Path(__file__).resolve().parent / "output"
_ANSI = re.compile(r"\x1b(?:\][^\x07]*(?:\x07|$)|\[[0-?]*[ -/]*[@-~]|[@-_])")
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class ReportIntegrityError(Exception):
    """A ledger inconsistency that prevents a trustworthy report."""


@dataclass(frozen=True)
class ReproductionStep:
    verifier_role: str
    snapshot_id: str
    method: str
    proposed_path: str
    resolved_path: str
    account: str
    executed: bool
    status_code: int


def safe_text(value: object) -> str:
    """Return display text with markup, terminal, and structural controls neutralized."""
    text = _ANSI.sub("[control]", "" if value is None else str(value))
    result: list[str] = []
    for character in text:
        if character in "\r\n":
            result.append(" ")
        elif ord(character) < 32 or ord(character) == 127 or unicodedata.category(character) in {"Cc", "Cf"}:
            result.append("[control]")
        else:
            result.append(character)
    return "".join(result).strip()


def markdown_text(value: object) -> str:
    """Escape all Markdown syntax that could alter report structure."""
    text = safe_text(value)
    return re.sub(r"([\\`*{}_\[\]<>()#+\-!.|])", r"\\\1", text)


def html_text(value: object) -> str:
    return html.escape(safe_text(value), quote=True)


def _required_text(value: object, finding_id: str, field: str) -> str:
    if not isinstance(value, str) or not safe_text(value):
        raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an invalid {field}")
    return safe_text(value)


def _parse_reproduction_steps(raw: str, finding_id: str) -> tuple[ReproductionStep, ...]:
    try:
        attempts = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReportIntegrityError(f"finding {finding_id} has malformed reproduction JSON") from exc
    if not isinstance(attempts, list) or not attempts:
        raise ReportIntegrityError(f"finding {finding_id} reproduction JSON must be a non-empty list")
    rendered: list[ReproductionStep] = []
    for attempt in attempts:
        if not isinstance(attempt, dict) or not isinstance(attempt.get("steps"), list) or not attempt["steps"]:
            raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an invalid attempt")
        role = _required_text(attempt.get("verifier_role"), finding_id, "verifier_role")
        snapshot = _required_text(attempt.get("snapshot_id"), finding_id, "snapshot_id")
        for step in attempt["steps"]:
            if not isinstance(step, dict):
                raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an invalid step")
            values = {key: _required_text(step.get(key), finding_id, key) for key in ("method", "proposed_path", "resolved_path", "account")}
            executed, status_code = step.get("executed"), step.get("status_code")
            if not isinstance(executed, bool):
                raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an invalid executed value")
            if executed is not True:
                raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an unexecuted step")
            if not isinstance(status_code, int) or isinstance(status_code, bool) or not 100 <= status_code <= 599:
                raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an invalid status_code value")
            rendered.append(ReproductionStep(
                verifier_role=role, snapshot_id=snapshot,
                method=values["method"], proposed_path=values["proposed_path"], resolved_path=values["resolved_path"],
                account=values["account"], executed=executed, status_code=status_code,
            ))
    return tuple(rendered)


def _parse_evidence_references(raw: str, finding_id: str) -> tuple[str, ...]:
    try:
        references = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReportIntegrityError(f"finding {finding_id} has malformed evidence references") from exc
    if not isinstance(references, list) or not references or any(not isinstance(reference, str) or not safe_text(reference) for reference in references):
        raise ReportIntegrityError(f"finding {finding_id} evidence references must be a non-empty list of strings")
    return tuple(safe_text(reference) for reference in references)


def _validate(view: RunView) -> tuple[dict[str, Finding], tuple[Hypothesis, ...]]:
    if view.run.agent_role != "verifier":
        raise ReportIntegrityError(f"run ID is not a verifier run: {view.run.id}")
    if view.run.status != "completed":
        raise ReportIntegrityError(f"verifier run is not completed: {view.run.id}")
    latest = {hypothesis.id: hypothesis for hypothesis in view.hypotheses}
    findings: dict[str, Finding] = {}
    for finding in view.findings:
        hypothesis = latest.get(finding.hypothesis_id)
        if hypothesis is None or hypothesis.verification_status != "verified":
            raise ReportIntegrityError(f"finding {finding.id} is linked to a hypothesis whose latest status is not verified")
        if finding.hypothesis_id in findings:
            raise ReportIntegrityError(f"multiple findings are linked to hypothesis {finding.hypothesis_id}")
        findings[finding.hypothesis_id] = finding
    missing = [h.id for h in latest.values() if h.verification_status == "verified" and h.id not in findings]
    if missing:
        raise ReportIntegrityError("verified hypothesis has no finding row: " + ", ".join(sorted(missing)))
    return findings, tuple(sorted(latest.values(), key=lambda item: item.id))


def _summary(hypotheses: tuple[Hypothesis, ...], findings: dict[str, Finding]) -> tuple[int, int, int, int]:
    verified = sum(1 for hypothesis in hypotheses if hypothesis.verification_status == "verified" and hypothesis.id in findings)
    unverified = sum(1 for hypothesis in hypotheses if hypothesis.verification_status == "unverified")
    inconclusive = sum(1 for hypothesis in hypotheses if hypothesis.verification_status == "inconclusive")
    other = len(hypotheses) - verified - unverified - inconclusive
    return verified, unverified, inconclusive, other


def _markdown_step(step: ReproductionStep) -> str:
    values = [
        ("Verifier role", step.verifier_role), ("Snapshot/reset ID", step.snapshot_id), ("Method", step.method),
        ("Proposed path", step.proposed_path), ("Resolved local path", step.resolved_path), ("Synthetic account", step.account),
        ("Executed", step.executed), ("Recorded status code", step.status_code),
    ]
    return "; ".join(f"{label}: {markdown_text(value)}" for label, value in values if value)


def render_markdown(view: RunView) -> str:
    findings, hypotheses = _validate(view)
    verified, unverified, inconclusive, other = _summary(hypotheses, findings)
    run = view.run
    lines = [
        "# Crack Contained Verification Report", "", f"Verifier run ID: `{markdown_text(run.id)}`", "",
        "## Scope and limitations", "",
        f"- Target/application version: {markdown_text(run.app_version)}", f"- Declared scope: {markdown_text(run.declared_scope)}",
        f"- Environment snapshot/reset identifier: {markdown_text(run.environment_snapshot_id)}", f"- Run start: {markdown_text(run.start_time)}",
        f"- Run end: {markdown_text(run.end_time)}", f"- Verifier run status: {markdown_text(run.status)}", "",
        "This report concerns a synthetic-data, disposable local environment only.", "",
        "- Local seeded demo application only", "- Synthetic accounts and data only", "- No public-network or production testing",
        "- No claim of complete security coverage", "- No compliance or certification claim",
        "- Results apply only to the recorded application version, scope, and snapshots", "",
        "## Result summary", "", f"- Verified findings: {verified}", f"- Unverified hypotheses: {unverified}",
        f"- Inconclusive hypotheses: {inconclusive}", f"- Failed or other statuses: {other}", "", "## Verified findings", "",
    ]
    if not findings:
        lines.append("No verified findings were recorded for this verifier run.")
    for hypothesis in hypotheses:
        finding = findings.get(hypothesis.id)
        if finding is None:
            continue
        lines.extend([f"### {markdown_text(hypothesis.concise_claim)}", "", f"- Finding ID: `{markdown_text(finding.id)}`", f"- Hypothesis ID: `{markdown_text(hypothesis.id)}`", f"- Intended rule: {markdown_text(hypothesis.affected_app_rule)}", f"- Expected evidence: {markdown_text(hypothesis.expected_evidence)}", f"- Impact: {markdown_text(finding.severity_rationale)}", f"- Remediation direction: {markdown_text(finding.remediation_direction)}", "- Evidence references:"])
        for reference in _parse_evidence_references(finding.evidence_references, finding.id):
            lines.append(f"  - {markdown_text(reference)}")
        lines.extend(["", "Safe reproduction steps:"])
        for index, step in enumerate(_parse_reproduction_steps(finding.reproduction_steps, finding.id), 1):
            lines.append(f"{index}. {_markdown_step(step)}")
        lines.append("")
    lines.extend(["## Other hypotheses", ""])
    others = [hypothesis for hypothesis in hypotheses if hypothesis.verification_status != "verified"]
    if not others:
        lines.append("No unverified, inconclusive, failed, or other hypotheses were recorded.")
    for hypothesis in others:
        lines.extend([f"### Hypothesis `{markdown_text(hypothesis.id)}`", f"- Claim: {markdown_text(hypothesis.concise_claim)}", f"- Intended rule: {markdown_text(hypothesis.affected_app_rule)}", f"- Expected evidence: {markdown_text(hypothesis.expected_evidence)}", f"- Recorded status: {markdown_text(hypothesis.verification_status)}", ""])
    lines.extend(["## Evidence timeline and run metadata", "", f"- Token budget: {run.token_budget}", f"- Time budget: {run.time_budget}", "", "| Sequence | Action type | Safe request/response summary | Artifact reference | Policy decision | Timestamp |", "| --- | --- | --- | --- | --- | --- |"])
    for event in view.events:
        lines.append("| " + " | ".join([str(event.sequence_number), markdown_text(event.action_type), markdown_text(event.request_response_summary), markdown_text(event.artifact_reference), markdown_text(event.policy_decision), markdown_text(event.timestamp)]) + " |")
    if not view.events:
        lines.append("| - | No events recorded | - | - | - | - |")
    return "\n".join(lines) + "\n"


def _html_definition(items: list[tuple[str, object]]) -> str:
    return "<dl>" + "".join(f"<dt>{html_text(label)}</dt><dd>{html_text(value)}</dd>" for label, value in items) + "</dl>"


def render_html(view: RunView) -> str:
    """Independently render the report facts as static semantic HTML."""
    findings, hypotheses = _validate(view)
    verified, unverified, inconclusive, other = _summary(hypotheses, findings)
    run = view.run
    scope = _html_definition([("Target/application version", run.app_version), ("Declared scope", run.declared_scope), ("Environment snapshot/reset identifier", run.environment_snapshot_id), ("Run start", run.start_time), ("Run end", run.end_time), ("Verifier run status", run.status)])
    finding_html: list[str] = []
    for hypothesis in hypotheses:
        finding = findings.get(hypothesis.id)
        if finding is None:
            continue
        details = _html_definition([("Finding ID", finding.id), ("Hypothesis ID", hypothesis.id), ("Intended rule", hypothesis.affected_app_rule), ("Expected evidence", hypothesis.expected_evidence), ("Impact", finding.severity_rationale), ("Remediation direction", finding.remediation_direction)])
        references = "".join(f"<li>{html_text(reference)}</li>" for reference in _parse_evidence_references(finding.evidence_references, finding.id))
        steps = "".join("<tr>" + "".join(f"<td>{html_text(value)}</td>" for value in (step.verifier_role, step.snapshot_id, step.method, step.proposed_path, step.resolved_path, step.account, str(step.executed), str(step.status_code))) + "</tr>" for step in _parse_reproduction_steps(finding.reproduction_steps, finding.id))
        finding_html.append(f"<article><h3>{html_text(hypothesis.concise_claim)}</h3>{details}<h4>Evidence references</h4><ul>{references}</ul><h4>Safe reproduction steps</h4><table><thead><tr><th>Verifier role</th><th>Snapshot/reset ID</th><th>Method</th><th>Proposed path</th><th>Resolved local path</th><th>Synthetic account</th><th>Executed</th><th>Recorded status code</th></tr></thead><tbody>{steps}</tbody></table></article>")
    other_html = "".join(f"<article><h3>Hypothesis {html_text(hypothesis.id)}</h3>{_html_definition([('Claim', hypothesis.concise_claim), ('Intended rule', hypothesis.affected_app_rule), ('Expected evidence', hypothesis.expected_evidence), ('Recorded status', hypothesis.verification_status)])}</article>" for hypothesis in hypotheses if hypothesis.verification_status != "verified") or "<p>No unverified, inconclusive, failed, or other hypotheses were recorded.</p>"
    events = "".join("<tr>" + "".join(f"<td>{html_text(value)}</td>" for value in (event.sequence_number, event.action_type, event.request_response_summary, event.artifact_reference, event.policy_decision, event.timestamp)) + "</tr>" for event in view.events) or "<tr><td colspan=\"6\">No events recorded.</td></tr>"
    findings_section = "".join(finding_html) or "<p>No verified findings were recorded for this verifier run.</p>"
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Crack Contained Verification Report</title><style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;line-height:1.5}}section,article{{margin:1.5rem 0;padding:1rem;border:1px solid #ccd}}table{{border-collapse:collapse;width:100%;overflow-wrap:anywhere}}th,td{{border:1px solid #bbb;padding:.45rem;text-align:left;vertical-align:top}}th{{background:#eef}}dt{{font-weight:700;margin-top:.5rem}}dd{{margin-left:0}}code{{overflow-wrap:anywhere}}</style></head>
<body><header><h1>Crack Contained Verification Report</h1><p>Verifier run ID: <code>{html_text(run.id)}</code></p></header>
<section><h2>Scope and limitations</h2>{scope}<p>This report concerns a synthetic-data, disposable local environment only.</p><ul><li>Local seeded demo application only</li><li>Synthetic accounts and data only</li><li>No public-network or production testing</li><li>No claim of complete security coverage</li><li>No compliance or certification claim</li><li>Results apply only to the recorded application version, scope, and snapshots</li></ul></section>
<section><h2>Result summary</h2><dl><dt>Verified findings</dt><dd>{verified}</dd><dt>Unverified hypotheses</dt><dd>{unverified}</dd><dt>Inconclusive hypotheses</dt><dd>{inconclusive}</dd><dt>Failed or other statuses</dt><dd>{other}</dd></dl></section>
<section><h2>Verified findings</h2>{findings_section}</section><section><h2>Other hypotheses</h2>{other_html}</section>
<section><h2>Evidence timeline and run metadata</h2>{_html_definition([('Token budget', run.token_budget), ('Time budget', run.time_budget)])}<table><thead><tr><th>Sequence</th><th>Action type</th><th>Safe request/response summary</th><th>Artifact reference</th><th>Policy decision</th><th>Timestamp</th></tr></thead><tbody>{events}</tbody></table></section></body></html>
'''


def report_paths(run_id: str, output_path: str | Path = _DEFAULT_OUTPUT) -> tuple[Path, Path]:
    safe_id = _UNSAFE_FILENAME.sub("-", run_id).strip(".-") or "verifier-run"
    digest = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    base = Path(output_path) / f"verification-{safe_id[:80]}-{digest}"
    return base.with_suffix(".md"), base.with_suffix(".html")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def generate(view: RunView, output_path: str | Path = _DEFAULT_OUTPUT) -> tuple[Path, Path]:
    markdown, rendered_html = render_markdown(view), render_html(view)
    markdown_path, html_path = report_paths(view.run.id, output_path)
    _atomic_write(markdown_path, markdown)
    _atomic_write(html_path, rendered_html)
    return markdown_path, html_path


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(f"invalid arguments: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="python -m reports.generate")
    selectors = parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--latest", action="store_true", help="generate from the latest completed verifier run")
    selectors.add_argument("--run-id", help="generate from one verifier run ID")
    return parser


def main(argv: list[str] | None = None, *, database_path: str | Path = _DEFAULT_DATABASE, output_path: str | Path = _DEFAULT_OUTPUT) -> int:
    try:
        args = _parser().parse_args(argv)
        view = read_latest_verifier_run(database_path) if args.latest else read_run(args.run_id, database_path)
        paths = generate(view, output_path)
        print(paths[0])
        print(paths[1])
        return 0
    except (LedgerReadError, ReportIntegrityError, ValueError, OSError) as exc:
        sys.stderr.write(f"report error: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
