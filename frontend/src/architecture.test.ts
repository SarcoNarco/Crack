import { describe, expect, it } from 'vitest'
import styles from './styles.css?raw'
import architectureSource from './architecture.ts?raw'
import mapSource from './ArchitectureMap.tsx?raw'
import {
  ARCHITECTURE_GRAPH,
  ARCHITECTURE_NODE_IDS,
  assertArchitectureGraph,
  deriveArchitectureEffect,
  deriveArchitectureMap,
  mapEventToArchitecture,
} from './architecture'
import { previewEvents } from './fixtures'
import { PRESENTATION_EVENT_TYPES, type PresentationEvent } from './types'

describe('Sprint 20 event-tied architecture markers', () => {
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

  it('uses only safe static labels and no Sprint 23 map choreography', () => {
    expect(ARCHITECTURE_GRAPH.nodes.map((node) => node.label)).toEqual([
      'Browser portal', 'FastAPI API', 'Grade lifecycle', 'Role and authentication', 'SQLite persistence', 'Submissions',
    ])
    expect(styles).toMatch(/aspect-ratio: 16 \/ 9/)
    expect(styles).toMatch(/\.architecture-map \{[^}]*overflow: hidden/)
    expect(styles).toMatch(/\.architecture-map \{ width: 728px; max-width: none;/)
    expect(styles).toMatch(/\.architecture-map-viewport \{ overflow-x: auto;/)
    expect(styles).toMatch(/image-rendering: pixelated/)
    expect(styles).not.toMatch(/@keyframes architecture-/)
    expect(styles).not.toMatch(/\.architecture-effect/)
    expect(styles).toMatch(/@media \(forced-colors: active\)/)
    expect(styles).toMatch(/CanvasText/)
    expect(styles).toMatch(/Highlight/)
  })

  it('keeps relation and effect mapping exhaustive for every accepted event type', () => {
    const events = [...previewEvents('success'), ...previewEvents('failure')] as PresentationEvent[]
    expect(new Set(events.map((event) => event.type))).toEqual(new Set(PRESENTATION_EVENT_TYPES))
    for (const event of events) {
      const relation = mapEventToArchitecture(event)
      const effect = deriveArchitectureEffect(event, relation)
      expect(effect.key).toBe(`architecture-effect-${event.sequence}`)
      expect(effect.label).toBeTruthy()
    }
  })

  it('uses one latest unique event effect with deterministic sequence keys', () => {
    const event = previewEvents('success').find((item) => item.type === 'verifier_a.call_recorded')!
    const duplicated = deriveArchitectureMap([event, event])
    const once = deriveArchitectureMap([event])
    const duplicateEffect = deriveArchitectureEffect(duplicated.event!, duplicated.relation!)
    const onceEffect = deriveArchitectureEffect(once.event!, once.relation!)
    expect(duplicateEffect).toEqual(onceEffect)
    const newer = { ...event, sequence: event.sequence + 100 }
    const newerMap = deriveArchitectureMap([newer])
    expect(deriveArchitectureEffect(newerMap.event!, newerMap.relation!).key).not.toBe(onceEffect.key)
    expect(duplicateEffect.kind).toBe('pickaxe')
  })

  it('allows tool effects only for active safe events and active verifier calls', () => {
    const events = previewEvents('success')
    const mapperActive = events.find((item) => item.type === 'mapper.activated')!
    expect(deriveArchitectureEffect(mapperActive, mapEventToArchitecture(mapperActive)).kind).toBe('scan')
    const mapperCompleted = events.find((item) => item.type === 'mapper.completed')!
    expect(deriveArchitectureEffect(mapperCompleted, mapEventToArchitecture(mapperCompleted))).toMatchObject({ kind: 'static', nodeId: null })
    const identityActive = events.find((item) => item.type === 'identity.student_b_discovery')!
    const failedIdentity = { ...identityActive, state: 'failed' as const }
    expect(deriveArchitectureEffect(failedIdentity, mapEventToArchitecture(failedIdentity))).toMatchObject({ kind: 'static', nodeId: null })

    for (const type of [
      'verifier_a.activated', 'verifier_a.plan_validated', 'verifier_a.reset_completed', 'verifier_a.check_completed', 'verifier_a.completed',
      'verifier_b.activated', 'verifier_b.plan_validated', 'verifier_b.reset_completed', 'verifier_b.check_completed', 'verifier_b.completed',
    ] as const) {
      const event = events.find((item) => item.type === type)!
      expect(deriveArchitectureEffect(event, mapEventToArchitecture(event))).toMatchObject({ kind: 'static', nodeId: null })
    }

    const safeCall = events.find((item) => item.type === 'verifier_a.call_recorded')!
    expect(deriveArchitectureEffect(safeCall, mapEventToArchitecture(safeCall)).kind).toBe('pickaxe')
    const safeVerifierBCall = events.find((item) => item.type === 'verifier_b.call_recorded')!
    expect(deriveArchitectureEffect(safeVerifierBCall, mapEventToArchitecture(safeVerifierBCall)).kind).toBe('beam')
    const unsafeCall = { ...safeCall, metadata: { ...safeCall.metadata, method: 'POST' } }
    expect(deriveArchitectureEffect(unsafeCall, mapEventToArchitecture(unsafeCall))).toMatchObject({ kind: 'static', nodeId: null })
  })

  it('keeps outside-target actors static and prevents event-derived or random effect sources', () => {
    const consensus = previewEvents('success').find((event) => event.type === 'consensus.completed')!
    const relation = mapEventToArchitecture(consensus)
    expect(deriveArchitectureEffect(consensus, relation)).toMatchObject({ kind: 'static', nodeId: null })
    expect(architectureSource).not.toMatch(/\b(?:setTimeout|setInterval|requestAnimationFrame|Date|Math\.random)\b/)
    expect(mapSource).not.toMatch(/\b(?:setInterval|requestAnimationFrame|Date|Math\.random)\b/)
  })
})
