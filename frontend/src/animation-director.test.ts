import { describe, expect, it, vi } from 'vitest'
import {
  AnimationDirector,
  INTERACTION_CYCLE_DURATION_MS,
  MAP_MOVEMENT_UNITS_PER_SECOND,
  RECORDED_REPLAY_MOVEMENT_UNITS_PER_SECOND,
  type AnimationDirectorState,
} from './animation-director'
import { previewEvents } from './fixtures'
import type { PresentationEvent, PresentationEventType } from './types'

const scheduler = {
  setTimeout: (callback: () => void, delayMs: number) => window.setTimeout(callback, delayMs),
  clearTimeout: (handle: unknown) => window.clearTimeout(handle as number),
}

function event(sequence: number, type: PresentationEventType, metadata: Record<string, unknown> = {}): PresentationEvent {
  return { ...previewEvents('success')[0], sequence, type, state: 'active', metadata }
}

function agent(state: AnimationDirectorState, agentId: string) {
  return state.agents.find((candidate) => candidate.agentId === agentId)!
}

describe('Sprint 24 animation director', () => {
  it('moves an agent on authored cardinal legs at 50 map units per second, then returns it to dock', () => {
    vi.useFakeTimers()
    try {
      const director = new AnimationDirector({ scheduler })
      director.enqueue(event(1, 'mapper.activated'))
      expect(agent(director.getState(), 'mapper')).toMatchObject({ x: 271, y: 478, direction: 'right', phase: 'walk' })

      // First authored mapper leg is 49 map units: 49 / 50 seconds.
      vi.advanceTimersByTime(979)
      expect(agent(director.getState(), 'mapper')).toMatchObject({ x: 271, y: 478, phase: 'walk' })
      vi.advanceTimersByTime(1)
      expect(agent(director.getState(), 'mapper')).toMatchObject({ x: 320, y: 478, direction: 'up', phase: 'walk' })
      expect(MAP_MOVEMENT_UNITS_PER_SECOND).toBe(50)

      vi.runAllTimers()
      expect(agent(director.getState(), 'mapper')).toMatchObject({ x: 271, y: 478, phase: 'docked' })
      expect(director.getState()).toMatchObject({ active: false, currentCue: null })
    } finally {
      vi.useRealTimers()
    }
  })

  it('uses default live speed and exposes the fixed recorded replay speed', () => {
    const live = new AnimationDirector({ scheduler })
    const recorded = new AnimationDirector({ scheduler, movementUnitsPerSecond: RECORDED_REPLAY_MOVEMENT_UNITS_PER_SECOND })
    expect(live.getState().movementUnitsPerSecond).toBe(MAP_MOVEMENT_UNITS_PER_SECOND)
    expect(recorded.getState().movementUnitsPerSecond).toBe(210)
    expect(MAP_MOVEMENT_UNITS_PER_SECOND).toBe(50)
  })

  it('emits finite 720 ms interaction cycles with the current one in state', () => {
    vi.useFakeTimers()
    try {
      const director = new AnimationDirector({ scheduler })
      director.enqueue(event(1, 'mapper.activated'))
      // Mapper route: 49 + 136 map units, then fixed face state.
      vi.advanceTimersByTime(980 + 2720 + 120)
      expect(agent(director.getState(), 'mapper')).toMatchObject({ phase: 'interact' })
      expect(director.getState().currentCycleIndex).toBe(1)
      vi.advanceTimersByTime(INTERACTION_CYCLE_DURATION_MS - 1)
      expect(director.getState().currentCycleIndex).toBe(1)
      vi.advanceTimersByTime(1)
      expect(director.getState().currentCycleIndex).toBe(2)
      vi.advanceTimersByTime(INTERACTION_CYCLE_DURATION_MS)
      expect(agent(director.getState(), 'mapper')).toMatchObject({ phase: 'acknowledge' })
      expect(director.getState().currentCycleIndex).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('deduplicates sequence IDs and sorts an accepted batch before choreography', () => {
    vi.useFakeTimers()
    try {
      const routes: string[] = []
      const director = new AnimationDirector({ scheduler, onStateChange: (state) => {
        if (state.currentCue?.routeId) routes.push(state.currentCue.routeId)
      } })
      expect(director.enqueue([
        event(20, 'verifier_a.call_recorded', { executed: true, method: 'GET', resolved_path: '/submissions/mine' }),
        event(10, 'mapper.activated'),
        event(10, 'mapper.activated'),
      ])).toBe(2)
      vi.runAllTimers()
      expect(routes.filter((route, index) => index === 0 || routes[index - 1] !== route)).toEqual([
        'mapper-to-fastapi-api',
        'verifier-a-to-submissions',
      ])
    } finally {
      vi.useRealTimers()
    }
  })

  it('rejects a late individual sequence instead of executing it out of order', () => {
    vi.useFakeTimers()
    try {
      const director = new AnimationDirector({ scheduler })
      expect(director.enqueue(event(20, 'mapper.activated'))).toBe(1)
      expect(director.enqueue(event(10, 'identity.student_b_discovery'))).toBe(0)
      vi.runAllTimers()
      expect(agent(director.getState(), 'authorization-tester')).toMatchObject({ phase: 'docked' })
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps Verifier B docked until Verifier A has returned', () => {
    vi.useFakeTimers()
    try {
      const snapshots: AnimationDirectorState[] = []
      const director = new AnimationDirector({ scheduler, onStateChange: (state) => snapshots.push(state) })
      director.enqueue([
        event(1, 'verifier_a.call_recorded', { executed: true, method: 'GET', resolved_path: '/submissions/mine' }),
        event(2, 'verifier_b.call_recorded', { executed: true, method: 'GET', resolved_path: '/submissions/mine' }),
      ])
      vi.runAllTimers()
      const firstVerifierBMovement = snapshots.findIndex((state) => agent(state, 'verifier-b').phase !== 'docked')
      expect(firstVerifierBMovement).toBeGreaterThan(0)
      expect(snapshots.slice(0, firstVerifierBMovement).some((state) => agent(state, 'verifier-a').phase === 'return')).toBe(true)
      expect(snapshots[firstVerifierBMovement - 1].agents.every((entry) => entry.phase === 'docked')).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('groups adjacent same-agent cues through the fixed transfer corridor before its final dock return', () => {
    vi.useFakeTimers()
    try {
      const snapshots: AnimationDirectorState[] = []
      const director = new AnimationDirector({ scheduler, onStateChange: (state) => snapshots.push(state) })
      director.enqueue([
        event(1, 'identity.student_b_discovery'),
        event(2, 'identity.student_a_retrieval'),
      ])
      // 717 map units to submissions at 50 units/s, then face, two cycles, acknowledge.
      vi.advanceTimersByTime(14_340 + 120 + (2 * INTERACTION_CYCLE_DURATION_MS) + 160)
      expect(director.getState().currentCue).toMatchObject({ routeId: 'authorization-tester-to-grade-lifecycle' })
      expect(director.getState().activeRouteId).toBe('submissions-to-grade-lifecycle')
      expect(agent(director.getState(), 'authorization-tester')).toMatchObject({ x: 814, y: 204, direction: 'down', phase: 'walk' })
      const transferStart = snapshots.findIndex((state) => state.currentCue?.routeId === 'authorization-tester-to-grade-lifecycle'
        && agent(state, 'authorization-tester').phase === 'walk')
      expect(transferStart).toBeGreaterThan(0)
      expect(snapshots.slice(0, transferStart).some((state) => agent(state, 'authorization-tester').phase === 'return')).toBe(false)
      vi.runAllTimers()
      expect(agent(director.getState(), 'authorization-tester')).toMatchObject({ x: 401, y: 478, phase: 'docked' })
    } finally {
      vi.useRealTimers()
    }
  })

  it('defers Verifier B without a completed Verifier A journey and schedules no waiting timer', () => {
    vi.useFakeTimers()
    try {
      const snapshots: AnimationDirectorState[] = []
      const director = new AnimationDirector({ scheduler, onStateChange: (state) => snapshots.push(state) })
      director.enqueue(event(1, 'verifier_b.call_recorded', { executed: true, method: 'GET', resolved_path: '/submissions/mine' }))
      vi.runAllTimers()
      expect(agent(director.getState(), 'verifier-b')).toMatchObject({ phase: 'docked' })
      expect(director.getState().statusText).toBe('Verifier B remains staged until Verifier A returns.')
      expect(vi.getTimerCount()).toBe(0)

      director.enqueue(event(2, 'verifier_a.call_recorded', { executed: true, method: 'GET', resolved_path: '/submissions/mine' }))
      vi.runAllTimers()
      const firstVerifierBMovement = snapshots.findIndex((state) => agent(state, 'verifier-b').phase !== 'docked')
      expect(firstVerifierBMovement).toBeGreaterThan(0)
      expect(snapshots.slice(0, firstVerifierBMovement).some((state) => agent(state, 'verifier-a').phase === 'return')).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('cancels stale timers on reset and makes an unmounted director inert', () => {
    vi.useFakeTimers()
    try {
      const director = new AnimationDirector({ scheduler })
      director.enqueue(event(1, 'mapper.activated'))
      director.reset()
      vi.runAllTimers()
      expect(director.getState()).toMatchObject({ active: false, currentCue: null })
      expect(director.getState().agents.every((entry) => entry.phase === 'docked')).toBe(true)

      director.enqueue(event(1, 'mapper.activated'))
      director.destroy()
      vi.runAllTimers()
      expect(director.enqueue(event(2, 'mapper.activated'))).toBe(0)
      expect(director.getState().agents.every((entry) => entry.phase === 'docked')).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('cancels current choreography immediately at a terminal failure', () => {
    vi.useFakeTimers()
    try {
      const director = new AnimationDirector({ scheduler, movementUnitsPerSecond: RECORDED_REPLAY_MOVEMENT_UNITS_PER_SECOND })
      director.enqueue(event(1, 'mapper.activated'))
      vi.advanceTimersByTime(500)
      expect(agent(director.getState(), 'mapper').phase).toBe('walk')

      director.enqueue({ ...event(2, 'session.failed'), state: 'failed' })
      expect(director.getState()).toMatchObject({ active: false, currentCue: null })
      expect(director.getState().agents.every((entry) => entry.phase === 'docked')).toBe(true)
      vi.runAllTimers()
      expect(director.getState().agents.every((entry) => entry.phase === 'docked')).toBe(true)
      expect(director.enqueue(event(3, 'mapper.activated'))).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('uses ordered static acknowledgement without walking in reduced-motion mode', () => {
    vi.useFakeTimers()
    try {
      const phases: string[] = []
      const director = new AnimationDirector({ scheduler, reducedMotion: true, onStateChange: (state) => {
        const current = state.currentCue
        if (current?.agentId) phases.push(agent(state, current.agentId).phase)
      } })
      director.enqueue([
        event(1, 'mapper.activated'),
        event(2, 'identity.student_b_discovery'),
      ])
      expect(agent(director.getState(), 'mapper')).toMatchObject({ x: 271, y: 478, phase: 'acknowledge' })
      expect(director.getState().currentCycleIndex).toBe(1)
      vi.runAllTimers()
      expect(phases).toContain('acknowledge')
      expect(phases).not.toContain('walk')
      expect(director.getState().agents.every((entry) => entry.phase === 'docked')).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('restarts an interrupted cue safely when reduced motion changes', () => {
    vi.useFakeTimers()
    try {
      const director = new AnimationDirector({ scheduler })
      director.enqueue(event(1, 'mapper.activated'))
      vi.advanceTimersByTime(200)
      director.setReducedMotion(true)
      expect(agent(director.getState(), 'mapper')).toMatchObject({ x: 271, y: 478, phase: 'acknowledge' })
      vi.runAllTimers()
      expect(director.getState()).toMatchObject({ active: false, currentCue: null, reducedMotion: true })
      expect(director.getState().agents.every((entry) => entry.phase === 'docked')).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })
})
