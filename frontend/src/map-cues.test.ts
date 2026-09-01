import { describe, expect, it } from 'vitest'
import { previewEvents } from './fixtures'
import { isMotionCue, mapEventToCue } from './map-cues'
import { PRESENTATION_EVENT_TYPES, type PresentationEvent, type PresentationEventType } from './types'

function event(type: PresentationEventType, metadata: Record<string, unknown> = {}): PresentationEvent {
  return {
    ...previewEvents('success')[0],
    sequence: 99,
    type,
    state: 'active',
    metadata,
  }
}

describe('Sprint 24 safe map cues', () => {
  it('maps every accepted event type exhaustively to a fixed cue or explicit no-motion', () => {
    for (const type of PRESENTATION_EVENT_TYPES) {
      const cue = mapEventToCue(event(type))
      expect(cue.caption).not.toBe('')
      expect(Number.isInteger(cue.cycles)).toBe(true)
      if (!isMotionCue(cue)) {
        expect(cue).toMatchObject({ agentId: null, roomId: null, routeId: null, actionId: 'none', cycles: 0 })
      }
    }
  })

  it('uses only authored fixed routes for active mapper and authorization boundary events', () => {
    expect(mapEventToCue(event('mapper.activated'))).toMatchObject({
      agentId: 'mapper', roomId: 'fastapi-api', routeId: 'mapper-to-fastapi-api', actionId: 'scan', cycles: 2,
    })
    expect(mapEventToCue(event('identity.student_b_discovery'))).toMatchObject({
      agentId: 'authorization-tester', roomId: 'submissions', routeId: 'authorization-tester-to-submissions', actionId: 'probe',
    })
    expect(mapEventToCue(event('identity.student_a_retrieval'))).toMatchObject({
      agentId: 'authorization-tester', roomId: 'grade-lifecycle', routeId: 'authorization-tester-to-grade-lifecycle', actionId: 'probe',
    })
  })

  it('allows verifier movement only for active allowlisted GET routes', () => {
    expect(mapEventToCue(event('verifier_a.call_recorded', { executed: true, method: 'GET', resolved_path: '/submissions/mine' }))).toMatchObject({
      agentId: 'verifier-a', roomId: 'submissions', routeId: 'verifier-a-to-submissions', actionId: 'inspect',
    })
    expect(mapEventToCue(event('verifier_b.call_recorded', { executed: true, method: 'GET', resolved_path: '/submissions/student-b/grade' }))).toMatchObject({
      agentId: 'verifier-b', roomId: 'grade-lifecycle', routeId: 'verifier-b-to-grade-lifecycle', actionId: 'inspect',
    })
    for (const metadata of [
      { executed: false, method: 'GET', resolved_path: '/submissions/mine' },
      { method: 'GET', resolved_path: '/submissions/mine' },
      { executed: true, method: 'POST', resolved_path: '/submissions/mine' },
      { executed: true, method: 'GET', resolved_path: '/not-allowed' },
      { executed: true, method: 'GET', resolved_path: '/submissions/../../grade' },
    ]) expect(isMotionCue(mapEventToCue(event('verifier_a.call_recorded', metadata)))).toBe(false)
  })

  it('never turns inactive or terminal events into movement', () => {
    const inactive = { ...event('mapper.activated'), state: 'completed' as const }
    expect(isMotionCue(mapEventToCue(inactive))).toBe(false)
    for (const type of ['identity_reset.completed', 'consensus.completed', 'finding.recorded', 'report.generated', 'session.failed'] as const) {
      expect(isMotionCue(mapEventToCue(event(type)))).toBe(false)
    }
  })

  it('never returns event-controlled prose or paths', () => {
    const injected = event('verifier_b.call_recorded', {
      executed: true,
      method: 'GET',
      resolved_path: '/submissions/student-b/grade',
      secret: 'never-render-this',
    })
    const cue = mapEventToCue({ ...injected, headline: 'untrusted headline', explanation: 'untrusted explanation' })
    expect(JSON.stringify(cue)).not.toContain('untrusted')
    expect(JSON.stringify(cue)).not.toContain('student-b')
    expect(JSON.stringify(cue)).not.toContain('secret')
  })
})
