export type EventState = 'pending' | 'active' | 'completed' | 'failed' | 'blocked'
export type StageKey =
  | 'preflight'
  | 'mapper'
  | 'authorization'
  | 'verifier_a'
  | 'verifier_b'
  | 'consensus'
  | 'report'

export interface PresentationEvent {
  session_id: string
  sequence: number
  type: string
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
