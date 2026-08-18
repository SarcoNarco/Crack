from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from coordinator.demo import DemoDependencies, run_demo


def _verification(verdict: str = "verified", finding_id: str | None = "finding-1") -> object:
    return SimpleNamespace(
        run_id="verifier-new", hypothesis_id="hyp-new", verdict=verdict, finding_id=finding_id,
        attempts=(SimpleNamespace(snapshot_id="reset-verifier-a"), SimpleNamespace(snapshot_id="reset-verifier-b")),
    )


def _dependencies(tmp_path: Path, *, hypothesis_ids: list[str] | None = None,
                  verdict: str = "verified", finding_id: str | None = "finding-1") -> tuple[DemoDependencies, dict[str, object]]:
    calls: dict[str, object] = {"order": []}
    report_root = tmp_path / "reports"

    def mark(name: str) -> None:
        calls["order"].append(name)  # type: ignore[index]

    def mapper(**kwargs: object) -> object:
        mark("mapper")
        path = kwargs["output_path"]
        assert isinstance(path, Path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"routes": []}', encoding="utf-8")
        return SimpleNamespace(routes=[])

    def identity(**kwargs: object) -> object:
        mark("identity")
        calls["identity_contract"] = kwargs["contract_path"]
        return SimpleNamespace(run_id="identity-new", hypothesis_ids=hypothesis_ids if hypothesis_ids is not None else ["hyp-new"])

    def verifier(hypothesis_id: str, **kwargs: object) -> object:
        mark("verifier")
        calls["verifier_hypothesis"] = hypothesis_id
        return _verification(verdict, finding_id)

    def reader(run_id: str, _database: Path) -> object:
        mark("view")
        calls["view_run"] = run_id
        return SimpleNamespace(run_id=run_id)

    def report(_view: object) -> tuple[Path, Path]:
        mark("report")
        report_root.mkdir(parents=True, exist_ok=True)
        markdown, html = report_root / "report.md", report_root / "report.html"
        markdown.write_text("stable markdown\n", encoding="utf-8")
        html.write_text("<!doctype html><p>stable</p>\n", encoding="utf-8")
        return markdown, html

    return DemoDependencies(
        health_check=lambda: {"status_code": 200},
        client_factory=lambda role: mark(f"client:{role}") or SimpleNamespace(role=role),
        mapper=mapper, resetter=lambda: mark("reset") or "reset-identity", identity=identity,
        verifier=verifier, view_reader=reader, view_formatter=lambda view: f"view {view.run_id}",
        report_generator=report,
    ), calls


def test_happy_path_uses_exact_handoffs_and_stable_reports(tmp_path: Path) -> None:
    deps, calls = _dependencies(tmp_path)
    output: list[str] = []
    result = run_demo(dependencies=deps, output_root=tmp_path / "demo", database_path=tmp_path / "ledger.db", emit=output.append)

    assert result.exit_code == 0
    assert calls["identity_contract"] == tmp_path / "demo" / result.session_id / "app_contract.json"
    assert calls["verifier_hypothesis"] == "hyp-new"
    assert calls["view_run"] == "verifier-new"
    assert calls["order"] == ["client:mapper", "client:identity", "client:verifier_a", "client:verifier_b", "mapper", "reset", "identity", "verifier", "view", "view", "report", "report"]
    manifest = json.loads(result.manifest_path.read_text())
    assert set(manifest) == {"session_id", "stage_statuses", "contract_path", "route_count", "identity_run_id", "hypothesis_id", "verifier_run_id", "verifier_verdict", "finding_id", "reset_identifiers", "terminal_view_status", "markdown_path", "html_path", "report_hashes", "timestamps"}
    assert manifest["report_hashes"]["markdown"] and manifest["report_hashes"]["html"]
    assert "DEMO VERIFIED" in output[-2]


def test_zero_or_multiple_hypotheses_fail_before_verifier_and_reports(tmp_path: Path) -> None:
    for values in ([], ["first", "second"]):
        deps, calls = _dependencies(tmp_path, hypothesis_ids=values)
        result = run_demo(dependencies=deps, output_root=tmp_path / str(len(values)), emit=lambda _text: None)
        assert result.exit_code == 2
        assert "verifier" not in calls["order"] and "report" not in calls["order"]


def test_unverified_inconclusive_and_missing_finding_are_not_success(tmp_path: Path) -> None:
    for verdict, finding_id, expected in (("unverified", None, 1), ("inconclusive", None, 1), ("verified", None, 2)):
        deps, _ = _dependencies(tmp_path, verdict=verdict, finding_id=finding_id)
        result = run_demo(dependencies=deps, output_root=tmp_path / f"{verdict}-{finding_id}", emit=lambda _text: None)
        assert result.exit_code == expected


def test_preflight_failure_never_leaks_raw_error_or_claims_success(tmp_path: Path) -> None:
    deps, _ = _dependencies(tmp_path)
    deps = DemoDependencies(**{**deps.__dict__, "health_check": lambda: (_ for _ in ()).throw(RuntimeError("raw-model-content-and-secret"))})
    output: list[str] = []
    result = run_demo(dependencies=deps, output_root=tmp_path / "failed", emit=output.append)
    assert result.exit_code == 2
    assert "raw-model-content-and-secret" not in "\n".join(output)
    assert "VERIFIED" not in "\n".join(output)


def test_module_has_no_configurable_target_or_shell_surface() -> None:
    source = Path(__file__).resolve().parents[1].joinpath("demo.py").read_text(encoding="utf-8")
    assert "subprocess" not in source and "os.system" not in source
    assert "target_host" not in source and "provider_url" not in source


def test_internal_session_override_cannot_traverse_output_root(tmp_path: Path) -> None:
    deps, _calls = _dependencies(tmp_path)
    with pytest.raises(ValueError, match="server-generated"):
        run_demo(dependencies=deps, output_root=tmp_path, session_id="../../reports/output")


def test_coordinator_progress_is_ordered_at_real_stage_boundaries(tmp_path: Path) -> None:
    deps, _calls = _dependencies(tmp_path)
    events: list[str] = []
    result = run_demo(
        dependencies=deps,
        output_root=tmp_path / "demo",
        database_path=tmp_path / "ledger.db",
        emit=lambda _text: None,
        progress=lambda **event: events.append(str(event["event_type"])),
    )

    assert result.exit_code == 0
    expected = [
        "preflight.started", "preflight.completed", "mapper.activated", "mapper.completed",
        "identity_reset.started", "identity_reset.completed", "identity.activated",
        "identity.completed", "report.started", "report.generated", "session.completed",
    ]
    assert events == expected


def test_incomplete_verifier_emits_failure_without_verdict_finding_or_report(tmp_path: Path) -> None:
    deps, _calls = _dependencies(tmp_path)

    def incomplete_verifier(_hypothesis_id: str, **kwargs: object) -> object:
        progress = kwargs["progress"]
        progress(
            event_type="verifier_a.activated", stage="verifier_a", state="active",
            logical_role="verifier_a", headline="Independent check 1 activated",
            explanation="The first sequential logical role started.", metadata={}, reference=None,
        )
        progress(
            event_type="verifier_a.completed", stage="verifier_a", state="completed",
            logical_role="verifier_a", headline="Independent check 1 completed",
            explanation="The first sequential logical role completed.",
            metadata={"satisfied": True}, reference="verifier://verifier_a/check",
        )
        progress(
            event_type="verifier_b.activated", stage="verifier_b", state="active",
            logical_role="verifier_b", headline="Independent check 2 activated",
            explanation="The second sequential logical role started.", metadata={}, reference=None,
        )
        raise RuntimeError("raw provider response that must not reach the browser")

    deps = DemoDependencies(**{**deps.__dict__, "verifier": incomplete_verifier})
    events: list[dict[str, object]] = []
    result = run_demo(
        dependencies=deps,
        output_root=tmp_path / "demo",
        emit=lambda _text: None,
        progress=lambda **event: events.append(event),
    )

    assert result.exit_code == 2 and result.verdict is None and result.finding_id is None
    assert events[-1]["event_type"] == "session.failed"
    assert events[-1]["stage"] == "verifier_b"
    assert "raw provider response" not in json.dumps(events)
    assert not any(
        event["event_type"] in {"consensus.completed", "finding.recorded", "report.generated"}
        for event in events
    )
