import type { ArchitectureNodeId } from './architecture'
import type { MapAgentId } from './map-layout'
import type { PresentationEvent } from './types'

export const MAP_ACTION_IDS = ['none', 'scan', 'probe', 'pickaxe', 'beam'] as const
export type MapActionId = typeof MAP_ACTION_IDS[number]

export const MAP_DURATION_CLASSES = ['brief', 'standard', 'extended'] as const
export type MapDurationClass = typeof MAP_DURATION_CLASSES[number]

/**
 * Safe, renderer-independent presentation instruction. Values are exclusively
 * fixed identifiers selected by this module; event text and metadata never
 * become cue content.
 */
export interface MapCue {
  readonly agentId: MapAgentId | null
  readonly roomId: ArchitectureNodeId | null
  readonly routeId: string | null
  readonly actionId: MapActionId
  readonly cycles: number
  readonly caption: string
  readonly durationClass: MapDurationClass
}

const NO_MOTION_CUE: MapCue = {
  agentId: null,
  roomId: null,
  routeId: null,
  actionId: 'none',
  cycles: 0,
  caption: 'Accepted event has no character movement.',
  durationClass: 'brief',
}

const MAPPER_FASTAPI_CUE: MapCue = {
  agentId: 'mapper',
  roomId: 'fastapi-api',
  routeId: 'mapper-to-fastapi-api',
  actionId: 'scan',
  cycles: 2,
  caption: 'Mapper is reviewing the fixed FastAPI API station.',
  durationClass: 'standard',
}

const AUTH_SUBMISSIONS_CUE: MapCue = {
  agentId: 'authorization-tester',
  roomId: 'submissions',
  routeId: 'authorization-tester-to-submissions',
  actionId: 'probe',
  cycles: 2,
  caption: 'Authorization Tester is reviewing the fixed submissions station.',
  durationClass: 'standard',
}

const AUTH_GRADE_CUE: MapCue = {
  agentId: 'authorization-tester',
  roomId: 'grade-lifecycle',
  routeId: 'authorization-tester-to-grade-lifecycle',
  actionId: 'probe',
  cycles: 2,
  caption: 'Authorization Tester is reviewing the fixed grade lifecycle station.',
  durationClass: 'standard',
}

const VERIFIER_A_SUBMISSIONS_CUE: MapCue = {
  agentId: 'verifier-a',
  roomId: 'submissions',
  routeId: 'verifier-a-to-submissions',
  actionId: 'pickaxe',
  cycles: 3,
  caption: 'Verifier A is reviewing a fixed submissions route.',
  durationClass: 'extended',
}

const VERIFIER_A_GRADE_CUE: MapCue = {
  agentId: 'verifier-a',
  roomId: 'grade-lifecycle',
  routeId: 'verifier-a-to-grade-lifecycle',
  actionId: 'pickaxe',
  cycles: 3,
  caption: 'Verifier A is reviewing a fixed grade lifecycle route.',
  durationClass: 'extended',
}

const VERIFIER_B_SUBMISSIONS_CUE: MapCue = {
  agentId: 'verifier-b',
  roomId: 'submissions',
  routeId: 'verifier-b-to-submissions',
  actionId: 'beam',
  cycles: 3,
  caption: 'Verifier B is reviewing a fixed submissions route.',
  durationClass: 'extended',
}

const VERIFIER_B_GRADE_CUE: MapCue = {
  agentId: 'verifier-b',
  roomId: 'grade-lifecycle',
  routeId: 'verifier-b-to-grade-lifecycle',
  actionId: 'beam',
  cycles: 3,
  caption: 'Verifier B is reviewing a fixed grade lifecycle route.',
  durationClass: 'extended',
}

const CONCRETE_SUBMISSION_GRADE_PATH = /^\/submissions\/[A-Za-z0-9_-]{1,100}\/grade$/

function isActiveSafeGet(event: PresentationEvent): event is PresentationEvent & { readonly metadata: Record<string, unknown> & { readonly method: 'GET'; readonly resolved_path: string } } {
  return event.state === 'active'
    && event.metadata.executed === true
    && event.metadata.method === 'GET'
    && typeof event.metadata.resolved_path === 'string'
}

function cueForVerifierCall(event: PresentationEvent, agent: 'verifier-a' | 'verifier-b'): MapCue {
  if (!isActiveSafeGet(event)) return NO_MOTION_CUE
  const path = event.metadata.resolved_path
  const submissions = agent === 'verifier-a' ? VERIFIER_A_SUBMISSIONS_CUE : VERIFIER_B_SUBMISSIONS_CUE
  const grades = agent === 'verifier-a' ? VERIFIER_A_GRADE_CUE : VERIFIER_B_GRADE_CUE
  if (path === '/submissions/mine') return submissions
  if (path === '/grades/mine' || CONCRETE_SUBMISSION_GRADE_PATH.test(path)) return grades
  return NO_MOTION_CUE
}

/**
 * Maps one accepted presentation event to a fixed safe cue. It is deliberately
 * exhaustive: every event type resolves to movement or the same explicit
 * no-motion cue, and no event-provided prose or path is exposed.
 */
export function mapEventToCue(event: PresentationEvent): MapCue {
  switch (event.type) {
    case 'mapper.activated':
      return event.state === 'active' ? MAPPER_FASTAPI_CUE : NO_MOTION_CUE
    case 'identity.student_b_discovery':
      return event.state === 'active' ? AUTH_SUBMISSIONS_CUE : NO_MOTION_CUE
    case 'identity.student_a_retrieval':
      return event.state === 'active' ? AUTH_GRADE_CUE : NO_MOTION_CUE
    case 'verifier_a.call_recorded':
      return cueForVerifierCall(event, 'verifier-a')
    case 'verifier_b.call_recorded':
      return cueForVerifierCall(event, 'verifier-b')
    case 'session.started':
    case 'session.completed':
    case 'session.failed':
    case 'preflight.started':
    case 'preflight.completed':
    case 'mapper.completed':
    case 'identity_reset.started':
    case 'identity_reset.completed':
    case 'identity.activated':
    case 'hypothesis.created':
    case 'identity.completed':
    case 'verifier_a.activated':
    case 'verifier_a.reset_completed':
    case 'verifier_a.plan_validated':
    case 'verifier_a.check_completed':
    case 'verifier_a.completed':
    case 'verifier_b.activated':
    case 'verifier_b.reset_completed':
    case 'verifier_b.plan_validated':
    case 'verifier_b.check_completed':
    case 'verifier_b.completed':
    case 'consensus.started':
    case 'consensus.completed':
    case 'finding.recorded':
    case 'report.started':
    case 'report.generated':
      return NO_MOTION_CUE
    default: {
      const exhaustive: never = event.type
      void exhaustive
      return NO_MOTION_CUE
    }
  }
}

export function isMotionCue(cue: MapCue): cue is MapCue & { readonly agentId: MapAgentId; readonly roomId: ArchitectureNodeId; readonly routeId: string } {
  return cue.agentId !== null && cue.roomId !== null && cue.routeId !== null
}
