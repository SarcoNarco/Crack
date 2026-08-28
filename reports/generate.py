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


@dataclass(frozen=True)
class ReproductionAttempt:
    verifier_role: str
    snapshot_id: str
    steps: tuple[ReproductionStep, ...]


@dataclass(frozen=True)
class VerificationAttempt:
    verifier_role: str
    snapshot_id: str
    logical_state_hash: str
    steps: tuple[ReproductionStep, ...]
    check_reason: str


@dataclass(frozen=True)
class VerificationOverview:
    hypothesis_id: str
    target_id: str
    retrieval_status_code: int
    shared_logical_state_hash: str
    attempts: tuple[VerificationAttempt, ...]
    is_school_portal: bool


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


def _parse_reproduction_attempts(raw: str, finding_id: str) -> tuple[ReproductionAttempt, ...]:
    try:
        attempts = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReportIntegrityError(f"finding {finding_id} has malformed reproduction JSON") from exc
    if not isinstance(attempts, list) or not attempts:
        raise ReportIntegrityError(f"finding {finding_id} reproduction JSON must be a non-empty list")
    rendered: list[ReproductionAttempt] = []
    for attempt in attempts:
        if not isinstance(attempt, dict) or not isinstance(attempt.get("steps"), list) or not attempt["steps"]:
            raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an invalid attempt")
        role = _required_text(attempt.get("verifier_role"), finding_id, "verifier_role")
        snapshot = _required_text(attempt.get("snapshot_id"), finding_id, "snapshot_id")
        rendered_steps: list[ReproductionStep] = []
        for step in attempt["steps"]:
            if not isinstance(step, dict):
                raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an invalid step")
            values = {key: _required_text(step.get(key), finding_id, key) for key in ("method", "proposed_path", "resolved_path")}
            actor = _required_text(step.get("role", step.get("account")), finding_id, "role")
            executed, status_code = step.get("executed"), step.get("status_code")
            if not isinstance(executed, bool):
                raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an invalid executed value")
            if executed is not True:
                raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an unexecuted step")
            if not isinstance(status_code, int) or isinstance(status_code, bool) or not 100 <= status_code <= 599:
                raise ReportIntegrityError(f"finding {finding_id} reproduction JSON has an invalid status_code value")
            rendered_steps.append(ReproductionStep(
                verifier_role=role, snapshot_id=snapshot,
                method=values["method"], proposed_path=values["proposed_path"], resolved_path=values["resolved_path"],
                account=actor, executed=executed, status_code=status_code,
            ))
        rendered.append(ReproductionAttempt(role, snapshot, tuple(rendered_steps)))
    return tuple(rendered)


def _parse_reproduction_steps(raw: str, finding_id: str) -> tuple[ReproductionStep, ...]:
    return tuple(
        step
        for attempt in _parse_reproduction_attempts(raw, finding_id)
        for step in attempt.steps
    )


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
    if any(hypothesis.affected_app_rule.startswith("WORKFLOW:") for hypothesis in latest.values()):
        raise ReportIntegrityError(
            "workflow verifier evidence is intentionally unsupported by this authorization-only report"
        )
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


def _event_payload(view: RunView, action_type: str) -> list[tuple[object, dict[str, object]]]:
    payloads: list[tuple[object, dict[str, object]]] = []
    for event in view.events:
        if event.action_type != action_type:
            continue
        try:
            payload = json.loads(event.request_response_summary)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReportIntegrityError(f"{action_type} event has malformed JSON") from exc
        if not isinstance(payload, dict):
            raise ReportIntegrityError(f"{action_type} event must contain a JSON object")
        payloads.append((event, payload))
    return payloads


def _snapshot_hash(snapshot_id: str, finding_id: str) -> str:
    marker = ":state-sha256:"
    reset_id, separator, logical_hash = snapshot_id.rpartition(marker)
    if not separator or not reset_id.startswith("reset:") or not re.fullmatch(r"[0-9a-fA-F]{16,64}", logical_hash):
        raise ReportIntegrityError(f"finding {finding_id} has an invalid reset snapshot identifier")
    return logical_hash.lower()


def _verification_overview(view: RunView, hypothesis: Hypothesis, finding: Finding) -> VerificationOverview:
    attempts = _parse_reproduction_attempts(finding.reproduction_steps, finding.id)
    if len(attempts) != 2 or {attempt.verifier_role for attempt in attempts} != {"verifier_a", "verifier_b"}:
        raise ReportIntegrityError(f"finding {finding.id} must contain verifier_a and verifier_b attempts")
    attempts = tuple(sorted(attempts, key=lambda item: item.verifier_role))
    if len({attempt.snapshot_id for attempt in attempts}) != 2:
        raise ReportIntegrityError(f"finding {finding.id} verifier attempts must use distinct reset identifiers")
    hashes = {_snapshot_hash(attempt.snapshot_id, finding.id) for attempt in attempts}
    if len(hashes) != 1:
        raise ReportIntegrityError(f"finding {finding.id} verifier attempts do not share one logical-state hash")

    reset_payloads = _event_payload(view, "verifier_environment_reset")
    plan_payloads = _event_payload(view, "verifier_plan_proposed")
    call_payloads = _event_payload(view, "verifier_call_result")
    check_payloads = _event_payload(view, "verifier_deterministic_check")
    verdict_payloads = _event_payload(view, "verifier_final_verdict")
    rendered_attempts: list[VerificationAttempt] = []
    retrieved_target_ids: set[str] = set()
    retrieval_status_codes: set[int] = set()
    school_portal = False

    for attempt in attempts:
        matching_resets = [
            (event, payload) for event, payload in reset_payloads
            if payload.get("verifier_role") == attempt.verifier_role
            and payload.get("snapshot_id") == attempt.snapshot_id
            and event.policy_decision == "allowed"
        ]
        if len(matching_resets) != 1:
            raise ReportIntegrityError(f"finding {finding.id} has incomplete reset evidence for {attempt.verifier_role}")

        matching_plans = [
            (event, payload) for event, payload in plan_payloads
            if payload.get("verifier_role") == attempt.verifier_role
            and payload.get("snapshot_id") == attempt.snapshot_id
            and event.policy_decision == "allowed"
        ]
        if len(matching_plans) != 1 or not isinstance(matching_plans[0][1].get("steps"), list):
            raise ReportIntegrityError(f"finding {finding.id} has incomplete isolated-plan evidence for {attempt.verifier_role}")
        if matching_plans[0][1].get("step_count") != len(attempt.steps):
            raise ReportIntegrityError(f"finding {finding.id} plan evidence does not match its reproduction steps")

        role_calls = [
            (event, payload) for event, payload in call_payloads
            if payload.get("verifier_role") == attempt.verifier_role
            and payload.get("snapshot_id") == attempt.snapshot_id
        ]
        if len(role_calls) != len(attempt.steps):
            raise ReportIntegrityError(f"finding {finding.id} has incomplete call evidence for {attempt.verifier_role}")
        for step, (event, payload) in zip(attempt.steps, role_calls, strict=True):
            response = payload.get("response")
            if not isinstance(response, dict) or (
                payload.get("role", payload.get("account")), payload.get("executed"), payload.get("method"),
                payload.get("proposed_path"), payload.get("resolved_path"), response.get("status_code"),
            ) != (
                step.account, step.executed, step.method, step.proposed_path,
                step.resolved_path, step.status_code,
            ) or event.policy_decision != "allowed":
                raise ReportIntegrityError(f"finding {finding.id} call evidence does not match its reproduction steps")

        is_school_attempt = any(step.account in {"student_a", "student_b"} for step in attempt.steps)
        if is_school_attempt:
            school_portal = True
            discovery_indexes = [
                index for index, step in enumerate(attempt.steps)
                if step.account == "student_b" and step.method == "GET"
                and step.resolved_path == "/submissions/mine" and 200 <= step.status_code < 300
            ]
            retrievals = [
                (index, step) for index, step in enumerate(attempt.steps)
                if step.account == "student_a" and step.method == "GET"
                and re.fullmatch(r"/submissions/[A-Za-z0-9_-]{1,100}/grade", step.resolved_path)
                and 200 <= step.status_code < 300
            ]
        else:
            discovery_indexes = [
                index for index, step in enumerate(attempt.steps)
                if step.account == "account_b" and step.method == "GET"
                and step.resolved_path == "/records/mine" and 200 <= step.status_code < 300
            ]
            retrievals = [
                (index, step) for index, step in enumerate(attempt.steps)
                if step.account == "account_a" and step.method == "GET"
                and step.resolved_path.startswith("/records/") and step.resolved_path != "/records/mine"
                and 200 <= step.status_code < 300
            ]
        if not discovery_indexes or not retrievals or retrievals[-1][0] <= discovery_indexes[0]:
            raise ReportIntegrityError(f"finding {finding.id} does not record bounded discovery followed by exact detail retrieval")
        resolved_target = retrievals[-1][1].resolved_path
        target_id = (
            resolved_target.removeprefix("/submissions/").removesuffix("/grade")
            if is_school_attempt
            else resolved_target.removeprefix("/records/")
        )
        retrieved_target_ids.add(target_id)
        retrieval_status_codes.add(retrievals[-1][1].status_code)

        matching_checks = [
            payload for _, payload in check_payloads
            if payload.get("verifier_role") == attempt.verifier_role
            and payload.get("snapshot_id") == attempt.snapshot_id
        ]
        if len(matching_checks) != 1 or matching_checks[0].get("satisfied") is not True:
            raise ReportIntegrityError(f"finding {finding.id} lacks a satisfied deterministic check for {attempt.verifier_role}")
        reason = _required_text(matching_checks[0].get("reason"), finding.id, "deterministic check reason")
        rendered_attempts.append(VerificationAttempt(
            verifier_role=attempt.verifier_role,
            snapshot_id=attempt.snapshot_id,
            logical_state_hash=next(iter(hashes)),
            steps=attempt.steps,
            check_reason=reason,
        ))

    if len(retrieved_target_ids) != 1:
        raise ReportIntegrityError(f"finding {finding.id} verifier attempts did not retrieve the same exact target")
    if len(retrieval_status_codes) != 1:
        raise ReportIntegrityError(f"finding {finding.id} verifier attempts did not record the same retrieval status")
    rule = safe_text(hypothesis.affected_app_rule).lower()
    if not re.search(r"\bowner(?:ship)?\b", rule) or "must" not in rule:
        raise ReportIntegrityError(f"finding {finding.id} lacks a validated ownership rule for its plain-language outcome")
    matching_verdicts = [
        payload for _, payload in verdict_payloads
        if payload.get("hypothesis_id") == hypothesis.id
    ]
    if len(matching_verdicts) != 1 or (
        matching_verdicts[0].get("verdict") != "verified"
        or matching_verdicts[0].get("verifier_a_satisfied") is not True
        or matching_verdicts[0].get("verifier_b_satisfied") is not True
    ):
        raise ReportIntegrityError(f"finding {finding.id} lacks a matching verified final verdict")
    return VerificationOverview(
        hypothesis_id=hypothesis.id,
        target_id=next(iter(retrieved_target_ids)),
        retrieval_status_code=next(iter(retrieval_status_codes)),
        shared_logical_state_hash=next(iter(hashes)),
        attempts=tuple(rendered_attempts),
        is_school_portal=school_portal,
    )


def _markdown_step(step: ReproductionStep) -> str:
    values = [
        ("Verifier role", step.verifier_role), ("Snapshot/reset ID", step.snapshot_id), ("Method", step.method),
        ("Proposed path", step.proposed_path), ("Resolved local path", step.resolved_path), ("Synthetic role", step.account),
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
        "- Local seeded demo application only", "- Synthetic identities and data only", "- No public-network or production testing",
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
    return '<dl class="definition-grid">' + "".join(
        f"<div><dt>{html_text(label)}</dt><dd>{html_text(value)}</dd></div>"
        for label, value in items
    ) + "</dl>"


_HTML_STYLES = r"""
:root {
  color-scheme: dark;
  --page: #0a0b0e;
  --surface: #121419;
  --surface-raised: #191c22;
  --surface-soft: #20242b;
  --line: #343942;
  --line-strong: #4a505b;
  --text: #f2f3f5;
  --muted: #a7adb7;
  --red: #ff3d46;
  --red-deep: #9d1f29;
  --orange: #ff8a34;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  --display: "Arial Black", "Helvetica Neue", Arial, system-ui, sans-serif;
  --body: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
html { background: var(--page); max-width: 100%; }
body {
  margin: 0;
  min-width: 0;
  max-width: 100%;
  overflow-x: hidden;
  color: var(--text);
  background:
    radial-gradient(circle at 82% 0%, rgba(255, 61, 70, .09), transparent 34rem),
    linear-gradient(180deg, #0d0f13 0, var(--page) 32rem);
  font: 400 1rem/1.65 var(--body);
}
body::before {
  content: "";
  display: block;
  height: 3px;
  background: linear-gradient(90deg, var(--red) 0 28%, var(--orange) 28% 38%, transparent 38%);
}
.shell { width: min(1180px, calc(100% - 2rem)); margin: 0 auto; padding: 2.75rem 0 5rem; }
.report-header { display: grid; gap: 1.5rem; padding-bottom: 2rem; border-bottom: 1px solid var(--line); }
.header-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 1.5rem; }
.eyebrow, .section-kicker, .metric-label, dt, th, summary, .attempt-label {
  font-size: .72rem;
  font-weight: 800;
  letter-spacing: .13em;
  line-height: 1.4;
  text-transform: uppercase;
}
.eyebrow { margin: 0 0 .55rem; color: var(--orange); }
h1, h2, h3, h4 { margin-top: 0; font-family: var(--display); line-height: 1.12; }
h1 { max-width: 850px; margin-bottom: .5rem; font-size: clamp(2rem, 5vw, 4.6rem); letter-spacing: -.045em; text-transform: uppercase; }
h2 { margin-bottom: .75rem; font-size: clamp(1.45rem, 2.5vw, 2.35rem); letter-spacing: -.025em; }
h3 { margin-bottom: .75rem; font-size: clamp(1.1rem, 2vw, 1.5rem); }
h4 { margin-bottom: .55rem; font-size: 1rem; }
p, ul, ol { margin-top: 0; }
code, .mono, td { font-family: var(--mono); }
code, .mono { overflow-wrap: anywhere; word-break: break-word; }
.scope-pill, .check-chip {
  display: inline-flex;
  align-items: center;
  gap: .45rem;
  border: 1px solid var(--line-strong);
  border-radius: 999px;
  padding: .45rem .75rem;
  font-size: .72rem;
  font-weight: 800;
  letter-spacing: .09em;
  line-height: 1.2;
  text-transform: uppercase;
}
.scope-pill { flex: 0 0 auto; color: var(--muted); background: rgba(255,255,255,.025); }
.scope-pill::before { content: ""; width: .5rem; height: .5rem; border-radius: 50%; background: var(--orange); }
.header-meta { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .75rem; }
.header-meta div, .metric, .attempt-card, .finding-card, details, .integrity-card {
  border: 1px solid var(--line);
  background: rgba(25, 28, 34, .82);
}
.header-meta div { min-width: 0; padding: .85rem 1rem; }
.header-meta span { display: block; margin-bottom: .2rem; color: var(--muted); font-size: .72rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.header-meta strong { display: block; overflow-wrap: anywhere; font-size: .92rem; }
main > section { padding: clamp(2.75rem, 7vw, 5.5rem) 0; border-bottom: 1px solid var(--line); }
.verdict-panel {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(250px, .75fr);
  gap: 1.5rem;
  padding: clamp(1.5rem, 4vw, 3rem);
  border: 1px solid var(--line-strong);
  border-left: 4px solid var(--red);
  background: linear-gradient(135deg, rgba(32,36,43,.96), rgba(18,20,25,.95));
  box-shadow: 0 28px 70px rgba(0,0,0,.28);
}
.verdict-panel::after { content: ""; position: absolute; top: -1px; right: 2rem; width: 7rem; height: 2px; background: var(--orange); }
.verdict-state { margin: 0 0 .8rem; color: var(--red); font: 900 clamp(2.6rem, 8vw, 6rem)/.9 var(--display); letter-spacing: -.055em; text-transform: uppercase; }
.lede { max-width: 720px; margin-bottom: 0; color: #d4d7dc; font-size: clamp(1.05rem, 2vw, 1.3rem); }
.metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .7rem; align-content: start; }
.metric { min-width: 0; padding: 1rem; }
.metric:first-child { grid-column: 1 / -1; border-color: var(--red-deep); }
.metric-value { display: block; margin-top: .15rem; overflow-wrap: anywhere; font: 900 clamp(1.55rem, 3vw, 2.4rem)/1 var(--display); }
.metric:first-child .metric-value { color: var(--red); }
.metric-label { color: var(--muted); }
.section-heading { max-width: 760px; margin-bottom: 1.75rem; }
.section-kicker { margin-bottom: .45rem; color: var(--orange); }
.section-heading > p:last-child { margin-bottom: 0; color: var(--muted); }
.story-flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .8rem; margin: 0; padding: 0; list-style: none; counter-reset: story; }
.story-flow li { position: relative; min-width: 0; padding: 1.2rem; border-top: 2px solid var(--line-strong); background: rgba(255,255,255,.025); counter-increment: story; }
.story-flow li::before { content: "0" counter(story); display: block; margin-bottom: 1rem; color: var(--orange); font: 900 .75rem var(--mono); letter-spacing: .12em; }
.story-flow strong { display: block; margin-bottom: .35rem; }
.finding-card { position: relative; overflow: hidden; padding: clamp(1.25rem, 3vw, 2rem); border-top: 3px solid var(--red); }
.finding-card::after { content: "VERIFIED EVIDENCE"; position: absolute; top: 1rem; right: 1rem; color: var(--red); font-size: .65rem; font-weight: 900; letter-spacing: .12em; }
.finding-card h3 { max-width: 830px; padding-right: 9rem; }
.finding-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .8rem; margin-top: 1.5rem; }
.finding-block { min-width: 0; padding: 1rem; background: var(--surface-soft); border-left: 2px solid var(--line-strong); }
.finding-block.accent { border-left-color: var(--orange); }
.finding-block p:last-child { margin-bottom: 0; }
.finding-ids { margin: .8rem 0 0; color: var(--muted); font-size: .8rem; }
.attempt-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
.attempt-card { min-width: 0; padding: 1.25rem; border-top: 2px solid var(--orange); }
.attempt-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 1rem; }
.attempt-label { color: var(--text); }
.check-chip { border-color: var(--red-deep); color: #ffd9d3; background: rgba(255,61,70,.08); }
.attempt-card .mono { display: block; color: var(--muted); font-size: .8rem; }
.attempt-card .check-reason { margin: 1rem 0 0; padding-top: 1rem; border-top: 1px solid var(--line); }
.shared-state { margin-top: 1rem; padding: 1rem 1.2rem; border: 1px dashed var(--line-strong); color: var(--muted); }
.shared-state strong { color: var(--text); }
.table-scroll { max-width: 100%; overflow-x: auto; border: 1px solid var(--line); background: var(--surface); }
table { width: 100%; border-collapse: collapse; }
th, td { min-width: 8.5rem; padding: .8rem; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; overflow-wrap: anywhere; word-break: break-word; font-size: .78rem; }
th { position: sticky; top: 0; color: var(--muted); background: #1b1e24; font-family: var(--body); }
tr:last-child td { border-bottom: 0; }
.reproduction-group + .reproduction-group { margin-top: 1.5rem; }
.account-b { color: #ffc092; }
.account-a { color: #ff8990; }
details { max-width: 100%; }
summary { cursor: pointer; padding: 1rem 1.15rem; color: var(--text); }
summary::marker { color: var(--orange); }
summary:focus-visible { outline: 3px solid var(--orange); outline-offset: 3px; }
.details-body { padding: 0 1.15rem 1.15rem; }
.details-body ul { margin-bottom: 0; padding-left: 1.2rem; }
.details-body li { overflow-wrap: anywhere; }
.definition-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; margin: 0; }
.definition-grid > div { min-width: 0; padding: .9rem 1rem; border: 1px solid var(--line); background: rgba(255,255,255,.02); }
dt { margin-bottom: .25rem; color: var(--muted); }
dd { margin: 0; overflow-wrap: anywhere; word-break: break-word; }
.scope-grid { display: grid; grid-template-columns: 1.1fr .9fr; gap: 1rem; }
.limitations { margin: 0; padding: 1.2rem 1.2rem 1.2rem 2.4rem; border: 1px solid var(--line); background: var(--surface); }
.limitations li + li { margin-top: .45rem; }
.other-hypotheses { margin-top: 1rem; }
.integrity-card { padding: 1.25rem; }
.integrity-note { margin: 1rem 0 0; color: var(--muted); font-size: .9rem; }
.no-findings { padding: 1.25rem; border: 1px solid var(--line); background: var(--surface); }
.report-header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; padding-bottom: 1.2rem; }
.report-name { margin: 0; font: 900 clamp(1rem, 2vw, 1.3rem)/1.2 var(--display); letter-spacing: .04em; text-transform: uppercase; }
.report-name span { color: var(--orange); }
.header-details { min-width: min(100%, 25rem); background: transparent; }
.header-details summary { padding: .55rem .8rem; }
.header-details .details-body { padding-top: .5rem; }
.outcome-section { padding: 2rem 0 3.25rem; }
.outcome-hero {
  position: relative;
  padding: clamp(1.4rem, 4vw, 3rem);
  border: 1px solid var(--line-strong);
  border-left: 4px solid var(--red);
  background: linear-gradient(135deg, rgba(32,36,43,.97), rgba(18,20,25,.96));
  box-shadow: 0 28px 70px rgba(0,0,0,.28);
}
.outcome-hero::after { content: ""; position: absolute; top: -1px; right: 2rem; width: 7rem; height: 2px; background: var(--orange); }
.outcome-grid { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(320px, .75fr); gap: clamp(1.5rem, 4vw, 3rem); align-items: start; }
.status-line { display: flex; align-items: center; gap: .7rem; margin-bottom: 1rem; color: #ffd8da; font-size: .76rem; font-weight: 900; letter-spacing: .11em; text-transform: uppercase; }
.status-line::before { content: "Verified"; padding: .35rem .6rem; border: 1px solid var(--red-deep); color: var(--red); background: rgba(255,61,70,.08); }
.outcome-title { max-width: 760px; margin-bottom: 1.1rem; font-size: clamp(2.35rem, 5.6vw, 5.2rem); letter-spacing: -.05em; text-transform: none; }
.tested-rule { max-width: 760px; margin: 0; color: #d4d7dc; font-size: clamp(1rem, 1.8vw, 1.2rem); }
.tested-rule strong { color: var(--text); }
.comparison { display: grid; gap: .75rem; }
.comparison h2 { margin-bottom: .2rem; font-size: 1.25rem; }
.comparison-card { padding: 1rem 1.1rem; border: 1px solid var(--line); background: rgba(10,11,14,.42); }
.comparison-card strong { display: block; margin-bottom: .35rem; font-size: .73rem; letter-spacing: .12em; text-transform: uppercase; }
.comparison-card p { margin-bottom: 0; }
.comparison-card.expected strong { color: var(--muted); }
.comparison-card.actual { border-color: var(--red-deep); }
.comparison-card.actual strong { color: var(--red); }
.answer-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .75rem; margin-top: 1.25rem; }
.answer-card { min-width: 0; padding: 1rem 1.1rem; border-top: 2px solid var(--line-strong); background: rgba(255,255,255,.025); }
.answer-card.fix { border-top-color: var(--orange); }
.answer-card h2 { margin-bottom: .35rem; font-size: 1rem; }
.answer-card p { margin-bottom: 0; color: #d4d7dc; font-size: .92rem; }
.proof-note { margin-top: 1rem; color: var(--muted); font-size: .88rem; }
.problem-fix-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; margin-top: 1.25rem; }
.problem-block, .fix-block { min-width: 0; padding: 1.2rem; background: var(--surface-soft); border-left: 3px solid var(--line-strong); }
.fix-block { border-left-color: var(--orange); }
.problem-block p:last-child, .fix-block p:last-child { margin-bottom: 0; }
.recorded-impact { color: var(--muted); font-size: .9rem; }
.technical-label { display: block; color: var(--muted); font: 700 .72rem/1.4 var(--mono); letter-spacing: .04em; }
.attempt-card h3 { margin-bottom: .2rem; }
.attempt-card details { margin-top: .8rem; background: rgba(255,255,255,.02); }
.attempt-card details summary { padding: .75rem; }
.attempt-card .check-reason { margin-bottom: 0; }
.same-data { margin-top: 1rem; padding: 1rem 1.2rem; border: 1px dashed var(--line-strong); }
.same-data p { margin: .25rem 0 .75rem; color: var(--muted); }
.same-data details { background: rgba(255,255,255,.02); }
.trust-explanation { margin-top: 1rem; padding: 1.2rem; border: 1px solid var(--line); background: var(--surface); }
.trust-explanation h3 { margin-bottom: .7rem; }
.trust-explanation ul { margin-bottom: 0; }
.trust-explanation li + li { margin-top: .4rem; }
.glossary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .75rem; }
.glossary-grid > div { padding: 1rem; border: 1px solid var(--line); background: var(--surface); }
.glossary-grid dt { color: var(--orange); }
.technical-details { margin-top: 1rem; }
@media (max-width: 800px) {
  .header-row, .attempt-head { align-items: flex-start; }
  .header-meta, .verdict-panel, .scope-grid, .outcome-grid { grid-template-columns: 1fr; }
  .answer-grid { grid-template-columns: 1fr; }
  .story-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 560px) {
  .shell { width: min(100% - 1rem, 1180px); padding-top: .65rem; }
  .report-header { display: flex; padding-bottom: .65rem; }
  .report-name { font-size: .78rem; }
  .scope-pill { padding: .35rem .5rem; font-size: .58rem; }
  .header-details { display: none; }
  .outcome-section { padding: .75rem 0 1.5rem; }
  .header-meta, .metrics, .story-flow, .finding-grid, .attempt-grid, .definition-grid, .problem-fix-grid, .glossary-grid { grid-template-columns: 1fr; }
  .metric:first-child { grid-column: auto; }
  .verdict-panel, .outcome-hero { padding: .8rem; }
  .outcome-hero::after { right: .8rem; width: 4rem; }
  .outcome-grid { gap: .65rem; }
  .section-kicker { margin-bottom: .2rem; font-size: .62rem; }
  .status-line { gap: .4rem; margin-bottom: .45rem; font-size: .58rem; }
  .status-line::before { padding: .22rem .4rem; }
  .outcome-title { margin-bottom: .5rem; font-size: 2rem; line-height: .98; }
  .tested-rule { font-size: .76rem; line-height: 1.4; }
  .comparison { gap: .35rem; }
  .comparison h2 { margin-bottom: 0; font-size: .92rem; }
  .comparison-card { padding: .5rem .65rem; }
  .comparison-card strong { margin-bottom: .15rem; font-size: .58rem; }
  .comparison-card p { font-size: .74rem; line-height: 1.35; }
  .answer-grid { gap: .3rem; margin-top: .55rem; }
  .answer-card { padding: .45rem .6rem; }
  .answer-card h2 { margin-bottom: .1rem; font-size: .75rem; }
  .answer-card p { font-size: .68rem; line-height: 1.3; }
  .finding-card h3 { padding-right: 0; padding-top: 1.5rem; }
  .finding-card::after { left: 1.25rem; right: auto; }
  th, td { min-width: 7.5rem; padding: .65rem; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
@media print {
  :root { color-scheme: light; --page: #fff; --surface: #fff; --surface-raised: #fff; --surface-soft: #f4f4f4; --line: #aaa; --line-strong: #555; --text: #111; --muted: #444; --red: #9b111e; --orange: #8a4200; }
  @page { margin: 14mm; }
  html, body { background: #fff !important; color: #111; }
  body::before, .verdict-panel::after, .outcome-hero::after { display: none; }
  .shell { width: 100%; padding: 0; }
  .report-header, main > section { padding: 1rem 0; }
  .verdict-panel, .outcome-hero, .header-meta div, .metric, .attempt-card, .finding-card, details, .integrity-card, .table-scroll { background: #fff !important; box-shadow: none; break-inside: avoid; }
  .story-flow li, .finding-block, .definition-grid > div, .comparison-card, .answer-card, .problem-block, .fix-block, .glossary-grid > div { background: #f5f5f5 !important; }
  .story-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .lede, .tested-rule, .answer-card p, .account-a, .account-b { color: #222; }
  details > :not(summary) { display: block !important; }
  summary { padding-left: 0; }
  .table-scroll { overflow: visible; }
  table { table-layout: fixed; }
  th, td { min-width: 0; padding: .35rem; font-size: 7.5pt; }
  .scope-pill, .check-chip, .status-line { color: #111; border-color: #555; background: #fff; }
}
"""


def render_html(view: RunView) -> str:
    """Render validated ledger facts as deterministic, standalone semantic HTML."""
    findings, hypotheses = _validate(view)
    verified, unverified, inconclusive, other = _summary(hypotheses, findings)
    run = view.run
    overviews = {
        hypothesis.id: _verification_overview(view, hypothesis, findings[hypothesis.id])
        for hypothesis in hypotheses if hypothesis.id in findings
    }
    stories: list[str] = []
    attempts_html: list[str] = []
    reproduction_html: list[str] = []
    finding_html: list[str] = []
    for hypothesis in hypotheses:
        finding = findings.get(hypothesis.id)
        if finding is None:
            continue
        overview = overviews[hypothesis.id]
        if overview.is_school_portal:
            story = f'''<ol class="story-flow">
<li><strong>Student B discovers their own submission</strong>The allowed <code>GET /submissions/mine</code> flow returns only Student B's submission.</li>
<li><strong>The exact submission ID is captured</strong><code>{html_text(overview.target_id)}</code> becomes the one submission both checks follow.</li>
<li><strong>Student A requests that submission detail</strong>The authenticated Student A flow requests the captured Student B submission and grade detail.</li>
<li><strong>Student A receives the same detail</strong>HTTP {html_text(overview.retrieval_status_code)} returns the exact Student B-owned submission and grade detail.</li>
</ol>'''
            finding_title = "Student A could read a submission and grade owned by Student B"
            impact = "The recorded rule requires student ownership enforcement, but the reproduction shows one authenticated student receiving another student's private submission and grade detail."
            shared_data = "Both fresh environments contained equivalent seeded Teacher, student, class, assignment, submission, and grade data."
            result_kind = "cross-student result"
        else:
            story = f'''<ol class="story-flow">
<li><strong>Account B discovers its own record</strong>The allowed <code>GET /records/mine</code> flow returns Account B's record.</li>
<li><strong>The exact record ID is captured</strong><code>{html_text(overview.target_id)}</code> becomes the one record both checks follow.</li>
<li><strong>Account A requests that record</strong>The authenticated Account A flow requests the captured Account B record.</li>
<li><strong>Account A receives the same record</strong>HTTP {html_text(overview.retrieval_status_code)} returns the exact Account B-owned record.</li>
</ol>'''
            finding_title = "Account A could read a record owned by Account B"
            impact = "The recorded rule requires ownership enforcement, but the reproduction shows one authenticated account receiving another account's data."
            shared_data = "Both fresh environments contained equivalent seeded accounts and records."
            result_kind = "cross-account result"
        stories.append(story)
        references = "".join(f"<li>{html_text(reference)}</li>" for reference in _parse_evidence_references(finding.evidence_references, finding.id))
        finding_html.append(f'''<article class="finding-card">
<h3>{html_text(finding_title)}</h3>
<div class="problem-fix-grid"><div class="problem-block"><h4>Why this is a real problem</h4><p>{html_text(impact)}</p><p class="recorded-impact">Recorded impact: {html_text(finding.severity_rationale)}</p></div><div class="fix-block"><h4>How to fix it</h4><p>{html_text(finding.remediation_direction)}</p></div></div>
<details class="technical-details"><summary>Technical finding details and evidence references</summary><div class="details-body">{_html_definition([('Finding ID', finding.id), ('Hypothesis ID', hypothesis.id), ('Recorded claim', hypothesis.concise_claim), ('Intended rule', hypothesis.affected_app_rule), ('Expected evidence', hypothesis.expected_evidence), ('Recorded impact', finding.severity_rationale)])}<h4>Evidence references</h4><ul class="mono">{references}</ul></div></details>
</article>''')
        attempt_cards: list[str] = []
        attempt_tables: list[str] = []
        for attempt_number, attempt in enumerate(overview.attempts, 1):
            role_label = attempt.verifier_role.replace("_", " ").title()
            attempt_cards.append(f'''<article class="attempt-card">
<div class="attempt-head"><div><h3>Independent check {attempt_number}</h3><span class="technical-label">{html_text(role_label)} · sequential logical role</span></div><span class="check-chip">Passed</span></div>
<p class="check-reason"><strong>Rule-based evidence check passed.</strong><span class="technical-label">Technical label · Deterministic check</span></p>
<p>{html_text(attempt.check_reason)}</p>
<details><summary>Fresh test environment</summary><div class="details-body">{_html_definition([('Technical label', 'Reset ID'), ('Exact reset ID', attempt.snapshot_id)])}</div></details>
</article>''')
            step_rows = "".join(
                f'''<tr class="reproduction-call"><td class="{html_text(step.account.replace('_', '-'))}">{html_text(step.account.replace('_', ' ').title())}</td><td>{html_text(step.method)}</td><td>{html_text(step.proposed_path)}</td><td>{html_text(step.resolved_path)}</td><td>{html_text(step.status_code)}</td><td>Executed</td></tr>'''
                for step in attempt.steps
            )
            attempt_tables.append(f'''<div class="reproduction-group"><h3>Independent check {attempt_number}</h3><span class="technical-label">{html_text(role_label)}</span><div class="table-scroll" tabindex="0" role="region" aria-label="Independent check {attempt_number} reproduction calls"><table><thead><tr><th>Synthetic role</th><th>Method</th><th>Proposed path</th><th>Resolved local path</th><th>Status</th><th>Execution</th></tr></thead><tbody>{step_rows}</tbody></table></div></div>''')
        attempts_html.append(f'''<div class="attempt-grid">{"".join(attempt_cards)}</div>
<div class="same-data"><strong>Same starting data</strong><p>{html_text(shared_data)}</p><details><summary>Technical value · Shared state hash</summary><div class="details-body"><code>{html_text(overview.shared_logical_state_hash)}</code></div></details></div>
<aside class="trust-explanation"><h3>Why two checks matter</h3><ul><li>They ran sequentially from separate fresh resets.</li><li>The shared state hash confirms equivalent seeded starting data.</li><li>Each check independently reproduced the same {html_text(result_kind)}.</li><li>The verifier design keeps plans and results isolated; neither check receives the other's plan or result.</li><li>The same ordinary-code evidence rule evaluated both results.</li></ul><p class="proof-note"><strong>Final decision made by ordinary code.</strong> The model-planned steps do not assign the verdict.</p></aside>''')
        reproduction_html.extend(attempt_tables)

    other_items = [hypothesis for hypothesis in hypotheses if hypothesis.verification_status != "verified"]
    other_html = "".join(
        f'''<details class="other-hypotheses"><summary>Other hypothesis · {html_text(hypothesis.verification_status)}</summary><div class="details-body">{_html_definition([('Hypothesis ID', hypothesis.id), ('Claim', hypothesis.concise_claim), ('Intended rule', hypothesis.affected_app_rule), ('Expected evidence', hypothesis.expected_evidence), ('Recorded status', hypothesis.verification_status)])}</div></details>'''
        for hypothesis in other_items
    ) or '<p class="no-findings">No unverified, inconclusive, failed, or other hypotheses were recorded.</p>'
    events = "".join(
        "<tr>" + "".join(
            f"<td>{html_text(value)}</td>" for value in (
                event.sequence_number, event.action_type, event.request_response_summary,
                event.artifact_reference, event.policy_decision, event.timestamp,
            )
        ) + "</tr>" for event in view.events
    ) or '<tr><td colspan="6">No events recorded.</td></tr>'
    findings_section = "".join(finding_html) or '<p class="no-findings">No verified findings were recorded for this verifier run.</p>'
    stories_section = "".join(stories) or '<p class="no-findings">The selected run contains no fully validated verified-finding narrative.</p>'
    attempts_section = "".join(attempts_html) or '<p class="no-findings">No verified independent-attempt evidence was recorded.</p>'
    reproduction_section = "".join(reproduction_html) or '<p class="no-findings">No verified reproduction steps were recorded.</p>'
    primary_hypothesis = next((hypothesis for hypothesis in hypotheses if hypothesis.id in findings), None)
    if primary_hypothesis is None:
        hero = '<div class="outcome-hero"><p class="section-kicker">Completed verifier run</p><h1 id="outcome-heading" class="outcome-title">No verified finding was recorded.</h1></div>'
    else:
        primary_finding = findings[primary_hypothesis.id]
        primary_overview = overviews[primary_hypothesis.id]
        if primary_overview.is_school_portal:
            outcome = "Student A could read Student B's submission and grade detail."
            expected = "Student A must not be able to retrieve Student B's private submission and grade detail."
            actual = f"Student A received Student B's exact submission and grade detail with HTTP {html_text(primary_overview.retrieval_status_code)}."
            proof = "Two sequential checks reproduced the same cross-student detail read."
        else:
            outcome = "Account A could read Account B's record."
            expected = "Account A must not be able to retrieve Account B's record."
            actual = f"Account A received Account B's exact record with HTTP {html_text(primary_overview.retrieval_status_code)}."
            proof = "Two sequential checks reproduced the same cross-account read."
        hero = f'''<div class="outcome-hero"><div class="outcome-grid"><div><p class="section-kicker">Recorded authorization failure</p><p id="verification-state" class="status-line">Evidence-backed finding</p><h1 id="outcome-heading" class="outcome-title">{outcome}</h1><p class="tested-rule"><strong>What the system tested:</strong> whether {html_text(primary_hypothesis.affected_app_rule)}.</p></div><div class="comparison" aria-labelledby="comparison-heading"><h2 id="comparison-heading">Expected vs actual</h2><div class="comparison-card expected"><strong>Expected</strong><p>{expected}</p></div><div class="comparison-card actual"><strong>Actual</strong><p>{actual}</p></div></div></div><div class="answer-grid"><div class="answer-card"><h2>How was it proven?</h2><p>{proof}</p></div><div class="answer-card"><h2>Why trust the result?</h2><p>Fresh resets, equivalent seeded data, and one ordinary-code rule.</p></div><div class="answer-card fix"><h2>What should the developer fix?</h2><p>{html_text(primary_finding.remediation_direction)}</p></div></div></div>'''
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Crack · Contained Verification Report</title><style>{_HTML_STYLES}</style></head>
<body><div class="shell">
<header class="report-header"><p class="report-name"><span>Crack</span> · Contained verification report</p><div><span class="scope-pill">Synthetic · Local only</span><details class="header-details"><summary>Report identity and run details</summary><div class="details-body">{_html_definition([('Target / application', run.app_version), ('Verifier run ID', run.id), ('Recorded run time', run.end_time)])}</div></details></div></header>
<main>
<section class="outcome-section" aria-labelledby="outcome-heading">{hero}</section>
<section aria-labelledby="story-heading"><div class="section-heading"><p class="section-kicker">Four-stage proof</p><h2 id="story-heading">How the failure happened</h2><p>The flow below is rendered from the validated calls and rule-based checks.</p></div>{stories_section}</section>
<section aria-labelledby="findings-heading"><div class="section-heading"><p class="section-kicker">Developer action</p><h2 id="findings-heading">Why it matters and how to fix it</h2></div>{findings_section}{other_html}</section>
<section aria-labelledby="verification-heading"><div class="section-heading"><p class="section-kicker">Two sequential checks</p><h2 id="verification-heading">Why the evidence is trustworthy</h2><p>The checks are isolated attempts run one after the other through logical verifier roles; they are not parallel services or spawned background processes.</p></div>{attempts_section}</section>
<section aria-labelledby="reproduction-heading"><div class="section-heading"><p class="section-kicker">Normal application flow</p><h2 id="reproduction-heading">Safe reproduction steps</h2><p>Calls are presented in their recorded order. Dense paths stay inside bounded, horizontally scrollable tables.</p></div>{reproduction_section}</section>
<section aria-labelledby="terms-heading"><div class="section-heading"><p class="section-kicker">Plain-language reference</p><h2 id="terms-heading">Technical terms explained</h2><p>These definitions describe how this local project works.</p></div><dl class="glossary-grid"><div><dt>Verifier</dt><dd>A logical checking role activated by the coordinator to propose one bounded reproduction plan. It is not a separate service or background process.</dd></div><div><dt>Fresh reset</dt><dd>The disposable demo app is returned to its known seeded starting data before one check begins.</dd></div><div><dt>Shared state hash</dt><dd>A fingerprint of the ordered seeded data showing that two fresh environments started equivalently. It is not a confidence score.</dd></div><div><dt>Deterministic / code-owned check</dt><dd>An ordinary Python rule evaluates the recorded responses the same way for both checks; model wording cannot assign the verdict.</dd></div><div><dt>Verified finding</dt><dd>A hypothesis that both sequential checks reproduced and that has a corresponding recorded finding.</dd></div></dl></section>
<section aria-labelledby="scope-heading"><div class="section-heading"><p class="section-kicker">Containment boundary</p><h2 id="scope-heading">Scope and limitations</h2></div><div class="scope-grid"><div>{_html_definition([('Target/application version', run.app_version), ('Declared scope', run.declared_scope), ('Run status', run.status)])}</div><ul class="limitations"><li>Local seeded demo application only</li><li>Synthetic identities and data only</li><li>No public-network or production testing</li><li>No claim of complete security coverage</li><li>No compliance or certification claim</li><li>Results apply only to the recorded application version, scope, and snapshots</li></ul></div></section>
<section aria-labelledby="timeline-heading"><div class="section-heading"><p class="section-kicker">Complete recorded trail</p><h2 id="timeline-heading">Technical evidence timeline</h2><p>The complete ordered ledger event stream remains available for technical review.</p></div><details><summary>Open complete evidence timeline · {len(view.events)} events</summary><div class="details-body"><div class="table-scroll" tabindex="0" role="region" aria-label="Complete technical evidence timeline"><table><thead><tr><th>Sequence</th><th>Action type</th><th>Safe request/response summary</th><th>Artifact reference</th><th>Policy decision</th><th>Timestamp</th></tr></thead><tbody>{events}</tbody></table></div></div></details></section>
<section aria-labelledby="integrity-heading"><div class="section-heading"><p class="section-kicker">Provenance</p><h2 id="integrity-heading">Report integrity and run metadata</h2></div><div class="integrity-card">{_html_definition([('Verifier run ID', run.id), ('Environment snapshot/reset identifiers', run.environment_snapshot_id), ('Run start', run.start_time), ('Run end', run.end_time), ('Verified findings', verified), ('Unverified hypotheses', unverified), ('Inconclusive hypotheses', inconclusive), ('Failed or other statuses', other), ('Token budget', run.token_budget), ('Time budget', run.time_budget), ('Run status', run.status)])}<p class="integrity-note">This standalone document contains static CSS only. It loads no network resources and executes no JavaScript.</p></div></section>
</main></div></body></html>
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
