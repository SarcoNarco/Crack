export type EventState = 'pending' | 'active' | 'completed' | 'failed' | 'blocked'
export type StageKey =
  | 'preflight'
  | 'mapper'
  | 'authorization'
  | 'verifier_a'
  | 'verifier_b'
  | 'consensus'
  | 'report'

export const PRESENTATION_EVENT_TYPES = [
  'session.started',
  'preflight.started', 'preflight.completed',
  'mapper.activated', 'mapper.completed',
  'identity_reset.started', 'identity_reset.completed',
  'identity.activated', 'identity.student_b_discovery', 'identity.student_a_retrieval',
  'hypothesis.created', 'identity.completed',
  'verifier_a.activated', 'verifier_a.reset_completed', 'verifier_a.plan_validated',
  'verifier_a.call_recorded', 'verifier_a.check_completed', 'verifier_a.completed',
  'verifier_b.activated', 'verifier_b.reset_completed', 'verifier_b.plan_validated',
  'verifier_b.call_recorded', 'verifier_b.check_completed', 'verifier_b.completed',
  'consensus.started', 'consensus.completed', 'finding.recorded',
  'report.started', 'report.generated',
  'session.completed', 'session.failed',
] as const

export type PresentationEventType = typeof PRESENTATION_EVENT_TYPES[number]

export function isPresentationEventType(value: unknown): value is PresentationEventType {
  return typeof value === 'string' && (PRESENTATION_EVENT_TYPES as readonly string[]).includes(value)
}

export interface PresentationEvent {
  session_id: string
  sequence: number
  type: PresentationEventType
  timestamp: string
  stage: StageKey | 'session'
  logical_role: string | null
  state: EventState
  headline: string
  explanation: string
  metadata: Record<string, unknown>
  reference: string | null
}

export interface RunStatus {
  session_id: string
  state: EventState
  stage: string
  last_sequence: number
  terminal: boolean
  events_url: string
}

export type DisplayMode = 'simple' | 'technical'
export type PreviewKind = 'success' | 'failure' | 'reconnect'

export const STAGES: Array<{ key: StageKey; label: string; short: string }> = [
  { key: 'preflight', label: 'Preflight', short: 'Fixed local readiness' },
  { key: 'mapper', label: 'Mapper', short: 'Source-only contract' },
  { key: 'authorization', label: 'Authorization tester', short: 'Student boundary' },
  { key: 'verifier_a', label: 'Independent check 1', short: 'Verifier A · sequential' },
  { key: 'verifier_b', label: 'Independent check 2', short: 'Verifier B · sequential' },
  { key: 'consensus', label: 'Code-owned consensus', short: 'Deterministic gate' },
  { key: 'report', label: 'Evidence report', short: 'Static output' },
]
