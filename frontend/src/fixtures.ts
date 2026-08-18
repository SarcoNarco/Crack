import type { PresentationEvent, PreviewKind } from './types'

const SESSION = 'demo:00000000-0000-4000-8000-000000000013'
const RESET_A = 'reset:preview-a:state-sha256:1bc3c2fa4a64fea8'
const RESET_B = 'reset:preview-b:state-sha256:1bc3c2fa4a64fea8'

type FixtureEvent = Omit<PresentationEvent, 'session_id' | 'sequence' | 'timestamp'>

function build(events: FixtureEvent[]): PresentationEvent[] {
  return events.map((event, sequence) => ({
    ...event,
    session_id: SESSION,
    sequence,
    timestamp: new Date(Date.UTC(2026, 7, 17, 8, 30, sequence)).toISOString(),
  }))
}

const successful = build([
  { type: 'session.started', stage: 'session', state: 'active', logical_role: 'coordinator', headline: 'Contained verification run accepted', explanation: 'This is recorded synthetic preview data using the production event schema.', metadata: { mode: 'preview' }, reference: null },
  { type: 'preflight.started', stage: 'preflight', state: 'active', logical_role: 'coordinator', headline: 'Fixed preflight started', explanation: 'Only the loopback app and committed role bindings are checked.', metadata: {}, reference: null },
  { type: 'preflight.completed', stage: 'preflight', state: 'completed', logical_role: 'coordinator', headline: 'Fixed preflight completed', explanation: 'The synthetic local dependencies were ready in this recorded fixture.', metadata: { role_bindings: ['mapper · groq · openai/gpt-oss-20b', 'identity · groq · openai/gpt-oss-120b', 'verifier_a · groq · openai/gpt-oss-120b', 'verifier_b · gemini · gemini-3.5-flash'] }, reference: null },
  { type: 'mapper.activated', stage: 'mapper', state: 'active', logical_role: 'mapper', headline: 'Source-only mapper activated', explanation: 'The mapper reads only the fixed source allowlist through the scope controller.', metadata: {}, reference: null },
  { type: 'mapper.completed', stage: 'mapper', state: 'completed', logical_role: 'mapper', headline: 'Application contract validated', explanation: 'The bounded app contract passed its schema.', metadata: { route_count: 6 }, reference: `demo://${SESSION}/app-contract` },
  { type: 'identity_reset.started', stage: 'authorization', state: 'active', logical_role: 'coordinator', headline: 'Authorization reset started', explanation: 'The disposable demo app returned to its seeded state.', metadata: {}, reference: null },
  { type: 'identity_reset.completed', stage: 'authorization', state: 'active', logical_role: 'coordinator', headline: 'Authorization reset completed', explanation: 'The fixed Account A, Account B, and note fixtures were restored.', metadata: { reset_id: 'reset:preview-identity:state-sha256:1bc3c2fa4a64fea8', state_hash: '1bc3c2fa4a64fea8' }, reference: 'scope-controller://reset_environment/preview-identity' },
  { type: 'identity.activated', stage: 'authorization', state: 'active', logical_role: 'identity', headline: 'Authorization tester activated', explanation: 'The logical role begins the two-call normal application flow.', metadata: {}, reference: null },
  { type: 'identity.account_b_discovery', stage: 'authorization', state: 'active', logical_role: 'identity', headline: 'Account B record discovery completed', explanation: 'Account B listed its own synthetic records.', metadata: { status_code: 200, record_id: 'note-account-b-001', owner_account: 'account_b' }, reference: 'scope-controller://call_app_endpoint/GET/records/mine' },
  { type: 'identity.account_a_retrieval', stage: 'authorization', state: 'active', logical_role: 'identity', headline: 'Account A cross-account retrieval completed', explanation: 'Account A requested the exact Account B record and received it.', metadata: { status_code: 200, requested_record_id: 'note-account-b-001', returned_record_id: 'note-account-b-001', returned_owner: 'account_b', exact_record_match: true }, reference: 'scope-controller://call_app_endpoint/GET/records/note-account-b-001' },
  { type: 'hypothesis.created', stage: 'authorization', state: 'active', logical_role: 'identity', headline: 'Unverified authorization hypothesis created', explanation: 'The hypothesis was created only after the exact cross-account return.', metadata: { hypothesis_id: 'hypothesis-preview-001' }, reference: 'ledger://hypothesis/hypothesis-preview-001' },
  { type: 'identity.completed', stage: 'authorization', state: 'completed', logical_role: 'identity', headline: 'Authorization test completed', explanation: 'The bounded authorization path produced one unverified hypothesis.', metadata: { identity_run_id: 'identity:preview-001', hypothesis_id: 'hypothesis-preview-001' }, reference: 'ledger://hypothesis/hypothesis-preview-001' },
  { type: 'verifier_a.activated', stage: 'verifier_a', state: 'active', logical_role: 'verifier_a', headline: 'Independent check 1 activated', explanation: 'Verifier A begins first as a logical role, not a separate process.', metadata: {}, reference: null },
  { type: 'verifier_a.reset_completed', stage: 'verifier_a', state: 'active', logical_role: 'verifier_a', headline: 'Fresh synthetic environment prepared', explanation: 'Independent check 1 received its own reset operation.', metadata: { reset_id: RESET_A, state_hash: '1bc3c2fa4a64fea8' }, reference: 'ledger://run/verifier:preview/event/0' },
  { type: 'verifier_a.plan_validated', stage: 'verifier_a', state: 'active', logical_role: 'verifier_a', headline: 'Bounded GET-only plan validated', explanation: 'Ordinary validation accepted two safe record-read calls.', metadata: { step_count: 2, plan_sha256: 'aaaaaaaaaaaaaaaa' }, reference: 'ledger://run/verifier:preview/event/1' },
  { type: 'verifier_a.call_recorded', stage: 'verifier_a', state: 'active', logical_role: 'verifier_a', headline: 'Bounded call 1 recorded', explanation: 'Account B record discovery returned HTTP 200.', metadata: { step_index: 1, account: 'account_b', method: 'GET', proposed_path: '/records/mine', resolved_path: '/records/mine', executed: true, status_code: 200, body_sha256: 'body-a1' }, reference: 'ledger://run/verifier:preview/event/2' },
  { type: 'verifier_a.call_recorded', stage: 'verifier_a', state: 'active', logical_role: 'verifier_a', headline: 'Bounded call 2 recorded', explanation: 'Account A received the exact Account B-owned record.', metadata: { step_index: 2, account: 'account_a', method: 'GET', proposed_path: '/records/{record_id}', resolved_path: '/records/note-account-b-001', executed: true, status_code: 200, body_sha256: 'body-a2' }, reference: 'ledger://run/verifier:preview/event/3' },
  { type: 'verifier_a.check_completed', stage: 'verifier_a', state: 'completed', logical_role: 'verifier_a', headline: 'Exact-record predicate evaluated', explanation: 'Account A received the exact record previously discovered as owned by Account B.', metadata: { satisfied: true, matching_step_indexes: [2] }, reference: 'ledger://run/verifier:preview/event/4' },
  { type: 'verifier_a.completed', stage: 'verifier_a', state: 'completed', logical_role: 'verifier_a', headline: 'Independent check 1 completed', explanation: 'Verifier A finished before Verifier B was activated.', metadata: { satisfied: true }, reference: 'ledger://run/verifier:preview/event/4' },
  { type: 'verifier_b.activated', stage: 'verifier_b', state: 'active', logical_role: 'verifier_b', headline: 'Independent check 2 activated', explanation: 'Verifier B begins sequentially after Verifier A completed.', metadata: {}, reference: null },
  { type: 'verifier_b.reset_completed', stage: 'verifier_b', state: 'active', logical_role: 'verifier_b', headline: 'Fresh synthetic environment prepared', explanation: 'Independent check 2 received a distinct reset operation.', metadata: { reset_id: RESET_B, state_hash: '1bc3c2fa4a64fea8' }, reference: 'ledger://run/verifier:preview/event/5' },
  { type: 'verifier_b.plan_validated', stage: 'verifier_b', state: 'active', logical_role: 'verifier_b', headline: 'Bounded GET-only plan validated', explanation: 'Ordinary validation accepted two safe record-read calls.', metadata: { step_count: 2, plan_sha256: 'bbbbbbbbbbbbbbbb' }, reference: 'ledger://run/verifier:preview/event/6' },
  { type: 'verifier_b.call_recorded', stage: 'verifier_b', state: 'active', logical_role: 'verifier_b', headline: 'Bounded call 1 recorded', explanation: 'Account B record discovery returned HTTP 200.', metadata: { step_index: 1, account: 'account_b', method: 'GET', proposed_path: '/records/mine', resolved_path: '/records/mine', executed: true, status_code: 200, body_sha256: 'body-b1' }, reference: 'ledger://run/verifier:preview/event/7' },
  { type: 'verifier_b.call_recorded', stage: 'verifier_b', state: 'active', logical_role: 'verifier_b', headline: 'Bounded call 2 recorded', explanation: 'Account A received the exact Account B-owned record.', metadata: { step_index: 2, account: 'account_a', method: 'GET', proposed_path: '/records/{record_id}', resolved_path: '/records/note-account-b-001', executed: true, status_code: 200, body_sha256: 'body-b2' }, reference: 'ledger://run/verifier:preview/event/8' },
  { type: 'verifier_b.check_completed', stage: 'verifier_b', state: 'completed', logical_role: 'verifier_b', headline: 'Exact-record predicate evaluated', explanation: 'Account A received the exact record previously discovered as owned by Account B.', metadata: { satisfied: true, matching_step_indexes: [2] }, reference: 'ledger://run/verifier:preview/event/9' },
  { type: 'verifier_b.completed', stage: 'verifier_b', state: 'completed', logical_role: 'verifier_b', headline: 'Independent check 2 completed', explanation: 'Verifier B completed its separately reset reproduction.', metadata: { satisfied: true }, reference: 'ledger://run/verifier:preview/event/9' },
  { type: 'consensus.started', stage: 'consensus', state: 'active', logical_role: 'ordinary_code', headline: 'Code-owned consensus evaluation started', explanation: 'Ordinary Python code compares the two deterministic checks.', metadata: { check_1_satisfied: true, check_2_satisfied: true }, reference: null },
  { type: 'consensus.completed', stage: 'consensus', state: 'completed', logical_role: 'ordinary_code', headline: 'Code-owned verdict: verified', explanation: 'Two deterministic passes produce a verified verdict.', metadata: { check_1_satisfied: true, check_2_satisfied: true, verdict: 'verified' }, reference: 'ledger://run/verifier:preview/event/10' },
  { type: 'finding.recorded', stage: 'consensus', state: 'completed', logical_role: 'ordinary_code', headline: 'Verified finding recorded', explanation: 'A finding was created only after both checks passed.', metadata: { finding_id: 'finding-preview-001', hypothesis_id: 'hypothesis-preview-001' }, reference: 'ledger://finding/finding-preview-001' },
  { type: 'report.started', stage: 'report', state: 'active', logical_role: 'reporter', headline: 'Deterministic report generation started', explanation: 'The exact completed verifier run is being rendered.', metadata: { verifier_run_id: 'verifier:preview-001' }, reference: 'ledger://run/verifier:preview-001' },
  { type: 'report.generated', stage: 'report', state: 'completed', logical_role: 'reporter', headline: 'Deterministic report generated', explanation: 'The static report was generated twice with identical bytes in this fixture.', metadata: { markdown_sha256: 'preview-markdown-hash', html_sha256: 'preview-html-hash', report_url: `/api/demo-runs/${SESSION}/report`, verifier_run_id: 'verifier:preview-001' }, reference: 'report://verifier:preview-001' },
  { type: 'session.completed', stage: 'session', state: 'completed', logical_role: 'coordinator', headline: 'Contained verification run completed', explanation: 'The recorded synthetic preview reached its terminal event.', metadata: { verdict: 'verified', verifier_run_id: 'verifier:preview-001', finding_id: 'finding-preview-001', report_url: `/api/demo-runs/${SESSION}/report` }, reference: 'ledger://run/verifier:preview-001' },
])

function fixture(event: PresentationEvent): FixtureEvent {
  const { session_id: _session, sequence: _sequence, timestamp: _timestamp, ...safe } = event
  return safe
}

const failed = build([
  fixture(successful[0]),
  fixture(successful[1]),
  fixture(successful[2]),
  { type: 'mapper.activated', stage: 'mapper', state: 'active', logical_role: 'mapper', headline: 'Source-only mapper activated', explanation: 'The mapper began its bounded source-only operation.', metadata: {}, reference: null },
  { type: 'session.failed', stage: 'mapper', state: 'failed', logical_role: 'coordinator', headline: 'Contained run stopped safely', explanation: 'The mapper did not complete; downstream roles were never activated and no verdict was created.', metadata: { failed_stage: 'mapper', error_code: 'stage_execution_failed' }, reference: null },
] satisfies FixtureEvent[])

export function previewEvents(kind: PreviewKind): PresentationEvent[] {
  if (kind === 'failure') return failed
  if (kind === 'reconnect') {
    return [...successful.slice(0, 18), ...successful.slice(12, 18), ...successful.slice(18)]
  }
  return successful
}
