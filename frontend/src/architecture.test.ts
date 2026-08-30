import { describe, expect, it } from 'vitest'
import styles from './styles.css?raw'
import {
  ARCHITECTURE_GRAPH,
  ARCHITECTURE_NODE_IDS,
  assertArchitectureGraph,
  deriveArchitectureMap,
  mapEventToArchitecture,
} from './architecture'
import { previewEvents } from './fixtures'
import type { PresentationEvent } from './types'

describe('Sprint 19 static architecture map', () => {
  it('uses the exact canonical Sprint 18 node and edge structure', () => {
    expect(ARCHITECTURE_GRAPH.nodes.map((node) => node.id)).toEqual(ARCHITECTURE_NODE_IDS)
    expect(ARCHITECTURE_GRAPH.edges).toHaveLength(9)
    expect(() => assertArchitectureGraph(ARCHITECTURE_GRAPH)).not.toThrow()
  })

  it('rejects changed identifiers, types, layers, coordinates, and edge order', () => {
    const invalid = {
      nodes: ARCHITECTURE_GRAPH.nodes.map((node) => ({ ...node, coordinates: { ...node.coordinates } })),
      edges: ARCHITECTURE_GRAPH.edges.map((edge) => ({ ...edge })),
    }
    invalid.nodes[0].type = 'service'
    expect(() => assertArchitectureGraph(invalid)).toThrow('Architecture graph is invalid.')
    const outOfBounds = {
      nodes: ARCHITECTURE_GRAPH.nodes.map((node) => ({ ...node, coordinates: { ...node.coordinates } })),
      edges: ARCHITECTURE_GRAPH.edges.map((edge) => ({ ...edge })),
    }
    outOfBounds.nodes[0].coordinates.x = 1.1
    expect(() => assertArchitectureGraph(outOfBounds)).toThrow('Architecture graph is invalid.')
    const reordered = {
      nodes: ARCHITECTURE_GRAPH.nodes.map((node) => ({ ...node, coordinates: { ...node.coordinates } })),
      edges: ARCHITECTURE_GRAPH.edges.map((edge) => ({ ...edge })),
    }
    reordered.edges.reverse()
    expect(() => assertArchitectureGraph(reordered)).toThrow('Architecture graph is invalid.')
  })

  it('maps mapper, identity, reset, and consensus events only to honest target scope', () => {
    const events = previewEvents('success')
    expect(mapEventToArchitecture(events.find((event) => event.type === 'mapper.completed')!).nodeIds).toEqual(['fastapi-api'])
    expect(mapEventToArchitecture(events.find((event) => event.type === 'identity_reset.completed')!).nodeIds).toEqual(['sqlite-persistence'])
    expect(mapEventToArchitecture(events.find((event) => event.type === 'identity.student_a_retrieval')!).nodeIds).toEqual(['role-authentication', 'submissions', 'grade-lifecycle'])
    expect(mapEventToArchitecture(events.find((event) => event.type === 'consensus.completed')!).nodeIds).toEqual([])
  })

  it('maps only safe resolved verifier GET paths to their canonical domains', () => {
    const base = previewEvents('success').find((event) => event.type === 'verifier_a.call_recorded')!
    expect(mapEventToArchitecture(base).nodeIds).toEqual(['role-authentication', 'submissions'])
    const concreteGrade = { ...base, metadata: { ...base.metadata, resolved_path: '/submissions/Student_A-001/grade' } }
    expect(mapEventToArchitecture(concreteGrade).nodeIds).toEqual(['role-authentication', 'submissions', 'grade-lifecycle'])
    const maximumLengthGrade = { ...base, metadata: { ...base.metadata, resolved_path: `/submissions/${'a'.repeat(100)}/grade` } }
    expect(mapEventToArchitecture(maximumLengthGrade).nodeIds).toEqual(['role-authentication', 'submissions', 'grade-lifecycle'])
    const grade = { ...base, metadata: { ...base.metadata, resolved_path: '/grades/mine' } }
    expect(mapEventToArchitecture(grade).nodeIds).toEqual(['role-authentication', 'grade-lifecycle'])
    for (const resolvedPath of [
      '/submissions//grade',
      '/submissions/../grade',
      '/submissions/a%2Fb/grade',
      '/submissions/a/b/grade',
      '/submissions/a/grade/',
      `/submissions/${'a'.repeat(101)}/grade`,
    ]) {
      expect(mapEventToArchitecture({ ...base, metadata: { ...base.metadata, resolved_path: resolvedPath } }).nodeIds).toEqual([])
    }
    const unsafeMethod = { ...base, metadata: { ...base.metadata, method: 'POST', resolved_path: '/submissions/Student_A-001/grade' } }
    expect(mapEventToArchitecture(unsafeMethod).nodeIds).toEqual([])
  })

  it('waits with no events and derives replay state from one latest unique sequence', () => {
    expect(deriveArchitectureMap([])).toMatchObject({ event: null, relation: null, relatedEdgeIds: [] })
    const events = previewEvents('success')
    const replay = deriveArchitectureMap([...events, ...events].reverse())
    const original = deriveArchitectureMap(events)
    expect(replay).toEqual(original)
    expect(replay.relation?.actor).toBe('Coordinator')
  })

  it('shows one sequential verifier role at a time', () => {
    const events = previewEvents('success')
    const verifierA = events.find((event) => event.type === 'verifier_a.activated')!
    const verifierB = events.find((event) => event.type === 'verifier_b.activated')!
    expect(deriveArchitectureMap([verifierA]).relation?.actor).toBe('Verifier A (sequential)')
    expect(deriveArchitectureMap([verifierA, verifierB]).relation?.actor).toBe('Verifier B (sequential)')
  })

  it('uses only safe static labels and map selectors have no motion declarations', () => {
    expect(ARCHITECTURE_GRAPH.nodes.map((node) => node.label)).toEqual([
      'Browser portal', 'FastAPI API', 'Grade lifecycle', 'Role and authentication', 'SQLite persistence', 'Submissions',
    ])
    const mapStyles = styles.slice(styles.indexOf('.architecture-section'), styles.indexOf('.primary-grid'))
    expect(mapStyles).not.toMatch(/@keyframes|animation|transition/)
  })

  it('keeps event mapping exhaustive at compile-time and runtime for every fixture type', () => {
    const eventTypes = new Set(previewEvents('success').map((event) => event.type))
    expect(eventTypes.size).toBeGreaterThan(20)
    for (const event of previewEvents('success') as PresentationEvent[]) expect(mapEventToArchitecture(event)).toBeDefined()
  })
})
