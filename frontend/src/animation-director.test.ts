import { describe, expect, it, vi } from 'vitest'
import { AnimationDirector, MAP_MOVEMENT_UNITS_PER_SECOND, type AnimationDirectorState } from './animation-director'
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
