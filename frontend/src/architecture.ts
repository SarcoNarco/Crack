import type { PresentationEvent } from './types'

export const ARCHITECTURE_NODE_IDS = [
  'browser-portal',
  'fastapi-api',
  'grade-lifecycle',
  'role-authentication',
  'sqlite-persistence',
  'submissions',
] as const

export type ArchitectureNodeId = typeof ARCHITECTURE_NODE_IDS[number]
export type ArchitectureNodeType = 'interface' | 'service' | 'boundary' | 'domain' | 'persistence'
export type ArchitectureLayer = 'presentation' | 'application' | 'security' | 'domain' | 'data'

export interface ArchitectureNode {
  id: ArchitectureNodeId
  label: string
  type: ArchitectureNodeType
  layer: ArchitectureLayer
  description: string
  coordinates: Readonly<{ x: number; y: number }>
}

export interface ArchitectureEdge {
  id: string
  source: ArchitectureNodeId
  target: ArchitectureNodeId
  label: string
}

export interface ArchitectureGraph {
  nodes: readonly ArchitectureNode[]
  edges: readonly ArchitectureEdge[]
}

export const ARCHITECTURE_GRAPH: ArchitectureGraph = {
  nodes: [
    { id: 'browser-portal', label: 'Browser portal', type: 'interface', layer: 'presentation', description: 'Static browser portal served by FastAPI.', coordinates: { x: 0.08, y: 0.5 } },
    { id: 'fastapi-api', label: 'FastAPI API', type: 'service', layer: 'application', description: 'Fixed school-portal HTTP routes.', coordinates: { x: 0.32, y: 0.5 } },
    { id: 'grade-lifecycle', label: 'Grade lifecycle', type: 'domain', layer: 'domain', description: 'Review and publication lifecycle for grades.', coordinates: { x: 0.72, y: 0.7 } },
    { id: 'role-authentication', label: 'Role and authentication', type: 'boundary', layer: 'security', description: 'Fixed role and bearer-authentication boundary.', coordinates: { x: 0.52, y: 0.2 } },
    { id: 'sqlite-persistence', label: 'SQLite persistence', type: 'persistence', layer: 'data', description: 'SQLite stores portal domain records.', coordinates: { x: 0.92, y: 0.5 } },
    { id: 'submissions', label: 'Submissions', type: 'domain', layer: 'domain', description: 'Student submission domain records.', coordinates: { x: 0.72, y: 0.32 } },
  ],
  edges: [
    { id: 'fastapi-api--serves--browser-portal', source: 'fastapi-api', target: 'browser-portal', label: 'serves static portal' },
    { id: 'fastapi-api--uses--role-authentication', source: 'fastapi-api', target: 'role-authentication', label: 'uses protected-route boundary' },
    { id: 'fastapi-api--uses--submissions', source: 'fastapi-api', target: 'submissions', label: 'exposes submission routes' },
    { id: 'fastapi-api--uses--grade-lifecycle', source: 'fastapi-api', target: 'grade-lifecycle', label: 'exposes grade routes' },
    { id: 'role-authentication--authorizes--submissions', source: 'role-authentication', target: 'submissions', label: 'authorizes submission access' },
    { id: 'role-authentication--authorizes--grade-lifecycle', source: 'role-authentication', target: 'grade-lifecycle', label: 'authorizes grade access' },
    { id: 'submissions--links--grade-lifecycle', source: 'submissions', target: 'grade-lifecycle', label: 'links submissions and grades' },
    { id: 'submissions--persists--sqlite-persistence', source: 'submissions', target: 'sqlite-persistence', label: 'persists submissions' },
    { id: 'grade-lifecycle--persists--sqlite-persistence', source: 'grade-lifecycle', target: 'sqlite-persistence', label: 'persists grades' },
  ],
}

const NODE_TYPES = new Set<ArchitectureNodeType>(['interface', 'service', 'boundary', 'domain', 'persistence'])
const LAYERS = new Set<ArchitectureLayer>(['presentation', 'application', 'security', 'domain', 'data'])
const EDGE_IDS = [
  'fastapi-api--serves--browser-portal',
  'fastapi-api--uses--role-authentication',
  'fastapi-api--uses--submissions',
  'fastapi-api--uses--grade-lifecycle',
  'role-authentication--authorizes--submissions',
  'role-authentication--authorizes--grade-lifecycle',
  'submissions--links--grade-lifecycle',
  'submissions--persists--sqlite-persistence',
  'grade-lifecycle--persists--sqlite-persistence',
] as const

const NODE_SHAPES = [
  { id: 'browser-portal', label: 'Browser portal', type: 'interface', layer: 'presentation', x: 0.08, y: 0.5 },
  { id: 'fastapi-api', label: 'FastAPI API', type: 'service', layer: 'application', x: 0.32, y: 0.5 },
  { id: 'grade-lifecycle', label: 'Grade lifecycle', type: 'domain', layer: 'domain', x: 0.72, y: 0.7 },
  { id: 'role-authentication', label: 'Role and authentication', type: 'boundary', layer: 'security', x: 0.52, y: 0.2 },
  { id: 'sqlite-persistence', label: 'SQLite persistence', type: 'persistence', layer: 'data', x: 0.92, y: 0.5 },
  { id: 'submissions', label: 'Submissions', type: 'domain', layer: 'domain', x: 0.72, y: 0.32 },
] as const

const EDGE_ENDPOINTS = [
  ['fastapi-api', 'browser-portal'],
  ['fastapi-api', 'role-authentication'],
  ['fastapi-api', 'submissions'],
  ['fastapi-api', 'grade-lifecycle'],
  ['role-authentication', 'submissions'],
  ['role-authentication', 'grade-lifecycle'],
  ['submissions', 'grade-lifecycle'],
  ['submissions', 'sqlite-persistence'],
  ['grade-lifecycle', 'sqlite-persistence'],
] as const

export function assertArchitectureGraph(graph: unknown): asserts graph is ArchitectureGraph {
  if (typeof graph !== 'object' || graph === null) throw new Error('Architecture graph is invalid.')
  const candidate = graph as { nodes?: unknown; edges?: unknown }
  if (!Array.isArray(candidate.nodes) || !Array.isArray(candidate.edges)) throw new Error('Architecture graph is invalid.')
  if (candidate.nodes.length !== ARCHITECTURE_NODE_IDS.length || candidate.edges.length !== EDGE_IDS.length) throw new Error('Architecture graph is invalid.')
  const nodeIds = new Set<string>()
  candidate.nodes.forEach((node, index) => {
    if (typeof node !== 'object' || node === null) throw new Error('Architecture graph is invalid.')
    const item = node as Partial<ArchitectureNode>
    const expected = NODE_SHAPES[index]
    if (
      item.id !== expected.id || item.label !== expected.label
      || item.type !== expected.type || !NODE_TYPES.has(item.type as ArchitectureNodeType)
      || item.layer !== expected.layer || !LAYERS.has(item.layer as ArchitectureLayer)
      || typeof item.description !== 'string' || !item.description
      || typeof item.coordinates !== 'object' || item.coordinates === null
      || !Number.isFinite(item.coordinates.x) || !Number.isFinite(item.coordinates.y)
      || item.coordinates.x < 0 || item.coordinates.x > 1 || item.coordinates.y < 0 || item.coordinates.y > 1
      || item.coordinates.x !== expected.x || item.coordinates.y !== expected.y
      || nodeIds.has(item.id)
    ) throw new Error('Architecture graph is invalid.')
    nodeIds.add(item.id)
  })
  candidate.edges.forEach((edge, index) => {
    if (typeof edge !== 'object' || edge === null) throw new Error('Architecture graph is invalid.')
    const item = edge as Partial<ArchitectureEdge>
    const [source, target] = EDGE_ENDPOINTS[index]
    if (
      item.id !== EDGE_IDS[index]
      || typeof item.label !== 'string' || !item.label
      || typeof item.source !== 'string' || typeof item.target !== 'string'
      || item.source !== source || item.target !== target
      || !nodeIds.has(item.source) || !nodeIds.has(item.target) || item.source === item.target
    ) throw new Error('Architecture graph is invalid.')
  })
}

assertArchitectureGraph(ARCHITECTURE_GRAPH)

export type ArchitectureActor =
  | 'Coordinator'
  | 'Mapper'
  | 'Identity checker'
  | 'Verifier A (sequential)'
  | 'Verifier B (sequential)'
  | 'Code-owned consensus'
  | 'Report renderer'

export interface ArchitectureRelation {
  actor: ArchitectureActor
  nodeIds: readonly ArchitectureNodeId[]
}

const OUTSIDE_TARGET: readonly ArchitectureNodeId[] = []
const API_STRUCTURE: readonly ArchitectureNodeId[] = ['fastapi-api']
const RESET_PERSISTENCE: readonly ArchitectureNodeId[] = ['sqlite-persistence']
const IDENTITY_DOMAIN: readonly ArchitectureNodeId[] = ['role-authentication', 'submissions', 'grade-lifecycle']
const SUBMISSION_ROUTE: readonly ArchitectureNodeId[] = ['role-authentication', 'submissions']
const GRADE_ROUTE: readonly ArchitectureNodeId[] = ['role-authentication', 'grade-lifecycle']
const SUBMISSION_GRADE_ROUTE: readonly ArchitectureNodeId[] = ['role-authentication', 'submissions', 'grade-lifecycle']
const VERIFIER_DOMAIN: readonly ArchitectureNodeId[] = ['submissions', 'grade-lifecycle']
const CONCRETE_SUBMISSION_GRADE_PATH = /^\/submissions\/[A-Za-z0-9_-]{1,100}\/grade$/

function relation(actor: ArchitectureActor, nodeIds: readonly ArchitectureNodeId[]): ArchitectureRelation {
  return { actor, nodeIds }
}

function verifierCallRelation(event: PresentationEvent, actor: Extract<ArchitectureActor, `Verifier ${string}`>): ArchitectureRelation {
  const { method, resolved_path: resolvedPath } = event.metadata
  if (method !== 'GET' || typeof resolvedPath !== 'string') return relation(actor, OUTSIDE_TARGET)
  if (resolvedPath === '/submissions/mine') return relation(actor, SUBMISSION_ROUTE)
  if (CONCRETE_SUBMISSION_GRADE_PATH.test(resolvedPath)) return relation(actor, SUBMISSION_GRADE_ROUTE)
  if (resolvedPath === '/grades/mine') return relation(actor, GRADE_ROUTE)
  return relation(actor, OUTSIDE_TARGET)
}

export function mapEventToArchitecture(event: PresentationEvent): ArchitectureRelation {
  switch (event.type) {
    case 'session.started':
    case 'session.completed':
    case 'session.failed':
    case 'preflight.started':
    case 'preflight.completed':
      return relation('Coordinator', OUTSIDE_TARGET)
    case 'mapper.activated':
    case 'mapper.completed':
      return relation('Mapper', API_STRUCTURE)
    case 'identity_reset.started':
    case 'identity_reset.completed':
      return relation('Coordinator', RESET_PERSISTENCE)
    case 'identity.activated':
    case 'identity.student_b_discovery':
    case 'identity.student_a_retrieval':
    case 'identity.completed':
      return relation('Identity checker', IDENTITY_DOMAIN)
    case 'hypothesis.created':
      return relation('Identity checker', OUTSIDE_TARGET)
    case 'verifier_a.activated':
    case 'verifier_a.plan_validated':
    case 'verifier_a.check_completed':
    case 'verifier_a.completed':
      return relation('Verifier A (sequential)', VERIFIER_DOMAIN)
    case 'verifier_a.reset_completed':
      return relation('Verifier A (sequential)', RESET_PERSISTENCE)
    case 'verifier_a.call_recorded':
      return verifierCallRelation(event, 'Verifier A (sequential)')
    case 'verifier_b.activated':
    case 'verifier_b.plan_validated':
    case 'verifier_b.check_completed':
    case 'verifier_b.completed':
      return relation('Verifier B (sequential)', VERIFIER_DOMAIN)
    case 'verifier_b.reset_completed':
      return relation('Verifier B (sequential)', RESET_PERSISTENCE)
    case 'verifier_b.call_recorded':
      return verifierCallRelation(event, 'Verifier B (sequential)')
    case 'consensus.started':
    case 'consensus.completed':
    case 'finding.recorded':
      return relation('Code-owned consensus', OUTSIDE_TARGET)
    case 'report.started':
    case 'report.generated':
      return relation('Report renderer', OUTSIDE_TARGET)
    default: {
      const exhaustive: never = event.type
      return exhaustive
    }
  }
}

export interface ArchitectureMapState {
  event: PresentationEvent | null
  relation: ArchitectureRelation | null
  relatedEdgeIds: readonly string[]
}

export function deriveArchitectureMap(events: readonly PresentationEvent[]): ArchitectureMapState {
  const seenSequences = new Set<number>()
  const ordered = [...events]
    .sort((left, right) => left.sequence - right.sequence)
    .filter((event) => !seenSequences.has(event.sequence) && seenSequences.add(event.sequence))
  const event = ordered.at(-1) ?? null
  const relation = event ? mapEventToArchitecture(event) : null
  const related = new Set(relation?.nodeIds ?? [])
  return {
    event,
    relation,
    relatedEdgeIds: ARCHITECTURE_GRAPH.edges
      .filter((edge) => related.has(edge.source) && related.has(edge.target))
      .map((edge) => edge.id),
  }
}
