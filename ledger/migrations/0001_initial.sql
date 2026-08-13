-- Crack Sprint 0 ledger schema.

CREATE TABLE IF NOT EXISTS run (
    id TEXT,
    app_version TEXT,
    environment_snapshot_id TEXT,
    agent_role TEXT,
    declared_scope TEXT,
    start_time TEXT,
    end_time TEXT,
    token_budget INTEGER,
    time_budget INTEGER,
    status TEXT
);

CREATE TABLE IF NOT EXISTS event (
    run_id TEXT,
    sequence_number INTEGER,
    action_type TEXT,
    request_response_summary TEXT,
    artifact_reference TEXT,
    policy_decision TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS hypothesis (
    id TEXT,
    submitted_by_run TEXT,
    affected_app_rule TEXT,
    concise_claim TEXT,
    expected_evidence TEXT,
    verification_status TEXT,
    verifier_run_id TEXT
);

CREATE TABLE IF NOT EXISTS finding (
    hypothesis_id TEXT,
    severity_rationale TEXT,
    reproduction_steps TEXT,
    evidence_references TEXT,
    remediation_direction TEXT
);
