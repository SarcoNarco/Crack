import { MAP_ROOMS, MAP_ROUTES, STAGING_SLOTS, type MapAgentId, type MapPoint, type MapRoute } from './map-layout'
import { isMotionCue, mapEventToCue, type MapCue, type MapDurationClass } from './map-cues'
import type { PresentationEvent } from './types'

export const MAP_MOVEMENT_UNITS_PER_SECOND = 50

export type CardinalDirection = 'up' | 'down' | 'left' | 'right'
export type AgentPhase = 'docked' | 'walk' | 'face' | 'interact' | 'acknowledge' | 'return'

export interface AnimationAgentState {
  readonly agentId: MapAgentId
  readonly x: number
  readonly y: number
  readonly direction: CardinalDirection
  readonly phase: AgentPhase
}

export interface AnimationDirectorState {
  readonly generation: number
  readonly active: boolean
  readonly currentCue: MapCue | null
  readonly statusText: string
  readonly reducedMotion: boolean
  readonly agents: readonly AnimationAgentState[]
}

export interface AnimationScheduler {
  setTimeout(callback: () => void, delayMs: number): unknown
  clearTimeout(handle: unknown): void
}

export interface AnimationDirectorOptions {
  readonly scheduler?: AnimationScheduler
  readonly reducedMotion?: boolean
  readonly onStateChange?: (state: AnimationDirectorState) => void
}

interface QueuedCue {
  readonly sequence: number
  readonly cue: MapCue
}

const PHASE_DURATION_MS: Readonly<Record<MapDurationClass, number>> = {
  brief: 120,
  standard: 180,
  extended: 240,
}
const FACE_DURATION_MS = 120
const ACKNOWLEDGE_DURATION_MS = 160

const defaultScheduler: AnimationScheduler = {
  setTimeout: (callback, delayMs) => globalThis.setTimeout(callback, delayMs),
  clearTimeout: (handle) => (globalThis.clearTimeout as (timer: unknown) => void)(handle),
}

function dockedAgents(): AnimationAgentState[] {
  return STAGING_SLOTS.map((slot) => ({
    agentId: slot.agentId,
    x: slot.dockPoint.x,
    y: slot.dockPoint.y,
    direction: 'up',
    phase: 'docked',
  }))
}

function directionBetween(start: MapPoint, end: MapPoint): CardinalDirection {
  if (start.x === end.x) return end.y < start.y ? 'up' : 'down'
  return end.x < start.x ? 'left' : 'right'
}

function movementDuration(start: MapPoint, end: MapPoint): number {
  return (Math.abs(end.x - start.x) + Math.abs(end.y - start.y)) / MAP_MOVEMENT_UNITS_PER_SECOND * 1000
}

function directionTowardRoom(roomId: NonNullable<MapCue['roomId']>, from: MapPoint): CardinalDirection {
  const room = MAP_ROOMS.find((candidate) => candidate.id === roomId)
  if (!room) return 'up'
  const center = { x: room.bounds.x + room.bounds.width / 2, y: room.bounds.y + room.bounds.height / 2 }
  return Math.abs(center.x - from.x) >= Math.abs(center.y - from.y)
    ? (center.x < from.x ? 'left' : 'right')
    : (center.y < from.y ? 'up' : 'down')
}

/**
 * Renderer-agnostic finite choreography queue. It owns no event acceptance,
 * browser UI, CSS, tools, audio, or preview replay clock.
 */
export class AnimationDirector {
  private readonly scheduler: AnimationScheduler
  private readonly listeners = new Set<(state: AnimationDirectorState) => void>()
  private readonly seenSequences = new Set<number>()
  private readonly queue: QueuedCue[] = []
  private agents = dockedAgents()
  private timer: unknown | null = null
  private generation = 0
  private lastAcceptedSequence = Number.NEGATIVE_INFINITY
  private verifierAHasReturned = false
  private currentCue: MapCue | null = null
  private reducedMotion: boolean
  private disposed = false

  constructor(options: AnimationDirectorOptions = {}) {
    this.scheduler = options.scheduler ?? defaultScheduler
    this.reducedMotion = options.reducedMotion ?? false
    if (options.onStateChange) this.listeners.add(options.onStateChange)
  }

  getState(): AnimationDirectorState {
    return {
      generation: this.generation,
      active: this.currentCue !== null || this.queue.length > 0,
      currentCue: this.currentCue,
      statusText: this.currentCue?.caption
        ?? (this.waitingForVerifierA() ? 'Verifier B remains staged until Verifier A returns.' : 'All agents are staged and ready.'),
      reducedMotion: this.reducedMotion,
      agents: this.agents.map((agent) => ({ ...agent })),
    }
  }

  subscribe(listener: (state: AnimationDirectorState) => void): () => void {
    if (this.disposed) return () => undefined
    this.listeners.add(listener)
    listener(this.getState())
    return () => this.listeners.delete(listener)
  }

  setReducedMotion(reducedMotion: boolean): void {
    if (this.disposed || this.reducedMotion === reducedMotion) return
    const interruptedCue = this.currentCue
    this.generation += 1
    this.reducedMotion = reducedMotion
    this.cancelCurrentWork(true)
    if (interruptedCue) this.queue.unshift({ sequence: Number.NEGATIVE_INFINITY, cue: interruptedCue })
    this.emit()
    this.startNext()
  }

  /** Queues accepted events once, sorting a supplied batch by sequence. */
  enqueue(events: PresentationEvent | readonly PresentationEvent[]): number {
    if (this.disposed) return 0
    const candidates = (Array.isArray(events) ? events : [events])
      .slice()
      .sort((left, right) => left.sequence - right.sequence)
    let accepted = 0
    for (const event of candidates) {
      if (this.seenSequences.has(event.sequence) || event.sequence <= this.lastAcceptedSequence) continue
      this.seenSequences.add(event.sequence)
      this.lastAcceptedSequence = event.sequence
      this.queue.push({ sequence: event.sequence, cue: mapEventToCue(event) })
      accepted += 1
    }
    this.queue.sort((left, right) => left.sequence - right.sequence)
    this.startNext()
    return accepted
  }

  /** Cancels movement, invalidates callbacks, clears replay deduplication, and restores staging. */
  reset(): void {
    if (this.disposed) return
    this.generation += 1
    this.cancelCurrentWork(true)
    this.seenSequences.clear()
    this.lastAcceptedSequence = Number.NEGATIVE_INFINITY
    this.verifierAHasReturned = false
    this.queue.length = 0
    this.currentCue = null
    this.agents = dockedAgents()
    this.emit()
  }

  /** Alias for component cleanup. No stale scheduled callback can revive a disposed director. */
  destroy(): void {
    if (this.disposed) return
    this.reset()
    this.disposed = true
    this.listeners.clear()
  }

  private startNext(): void {
    if (this.disposed || this.currentCue !== null) return
    const nextIndex = this.queue.findIndex((entry) => this.canStart(entry.cue))
    const next = nextIndex < 0 ? undefined : this.queue.splice(nextIndex, 1)[0]
    if (!next) {
      this.emit()
      return
    }
    this.currentCue = next.cue
    this.emit()
    if (!isMotionCue(next.cue)) {
      this.currentCue = null
      this.emit()
      this.startNext()
      return
    }
    const route = this.routeFor(next.cue)
    if (!route) {
      this.currentCue = null
      this.emit()
      this.startNext()
      return
    }
    const generation = this.generation
    if (this.reducedMotion) {
      this.setAgent(next.cue.agentId, {
        direction: directionTowardRoom(next.cue.roomId, route.waypoints.at(-1)!),
        phase: 'acknowledge',
      })
      this.emit()
      this.schedule(generation, this.cueStaticDuration(next.cue), () => this.completeCue(generation))
      return
    }
    this.walkRoute(generation, next.cue, route, 1, 'walk')
  }

  private routeFor(cue: MapCue & { readonly agentId: MapAgentId; readonly roomId: NonNullable<MapCue['roomId']>; readonly routeId: string }): MapRoute | null {
    const route = MAP_ROUTES.find((candidate) => candidate.id === cue.routeId)
    return route && route.agentId === cue.agentId && route.roomId === cue.roomId ? route : null
  }

  private walkRoute(
    generation: number,
    cue: MapCue & { readonly agentId: MapAgentId; readonly roomId: NonNullable<MapCue['roomId']>; readonly routeId: string },
    route: MapRoute,
    targetIndex: number,
    phase: 'walk' | 'return',
  ): void {
    if (generation !== this.generation || this.disposed) return
    const points = phase === 'walk' ? route.waypoints : [...route.waypoints].reverse()
    const start = points[targetIndex - 1]
    const end = points[targetIndex]
    this.setAgent(cue.agentId, { x: start.x, y: start.y, direction: directionBetween(start, end), phase })
    this.emit()
    this.schedule(generation, movementDuration(start, end), () => {
      if (generation !== this.generation || this.disposed) return
      this.setAgent(cue.agentId, { x: end.x, y: end.y, direction: directionBetween(start, end), phase })
      this.emit()
      if (targetIndex < points.length - 1) {
        this.walkRoute(generation, cue, route, targetIndex + 1, phase)
        return
      }
      if (phase === 'return') {
        this.setAgent(cue.agentId, { phase: 'docked' })
        this.emit()
        this.completeCue(generation)
        return
      }
      this.faceTarget(generation, cue, route)
    })
  }

  private faceTarget(
    generation: number,
    cue: MapCue & { readonly agentId: MapAgentId; readonly roomId: NonNullable<MapCue['roomId']>; readonly routeId: string },
    route: MapRoute,
  ): void {
    const target = route.waypoints.at(-1)!
    this.setAgent(cue.agentId, { direction: directionTowardRoom(cue.roomId, target), phase: 'face' })
    this.emit()
    this.schedule(generation, FACE_DURATION_MS, () => this.interact(generation, cue, route))
  }

  private interact(
    generation: number,
    cue: MapCue & { readonly agentId: MapAgentId; readonly roomId: NonNullable<MapCue['roomId']>; readonly routeId: string },
    route: MapRoute,
  ): void {
    if (generation !== this.generation || this.disposed) return
    this.setAgent(cue.agentId, { phase: 'interact' })
    this.emit()
    this.schedule(generation, PHASE_DURATION_MS[cue.durationClass] * cue.cycles, () => {
      if (generation !== this.generation || this.disposed) return
      this.setAgent(cue.agentId, { phase: 'acknowledge' })
      this.emit()
      this.schedule(generation, ACKNOWLEDGE_DURATION_MS, () => this.walkRoute(generation, cue, route, 1, 'return'))
    })
  }

  private cueStaticDuration(cue: MapCue): number {
    return PHASE_DURATION_MS[cue.durationClass] * Math.max(1, cue.cycles) + ACKNOWLEDGE_DURATION_MS
  }

  private completeCue(generation: number): void {
    if (generation !== this.generation || this.disposed) return
    if (this.currentCue?.agentId === 'verifier-a') this.verifierAHasReturned = true
    this.agents = dockedAgents()
    this.currentCue = null
    this.emit()
    this.startNext()
  }

  private schedule(generation: number, delayMs: number, callback: () => void): void {
    this.clearTimer()
    this.timer = this.scheduler.setTimeout(() => {
      this.timer = null
      if (generation === this.generation && !this.disposed) callback()
    }, delayMs)
  }

  private cancelCurrentWork(clearCurrentCue: boolean): void {
    this.clearTimer()
    if (clearCurrentCue) this.currentCue = null
    this.agents = dockedAgents()
  }

  private clearTimer(): void {
    if (this.timer === null) return
    this.scheduler.clearTimeout(this.timer)
    this.timer = null
  }

  private canStart(cue: MapCue): boolean {
    return cue.agentId !== 'verifier-b' || this.verifierAHasReturned
  }

  private waitingForVerifierA(): boolean {
    return !this.verifierAHasReturned && this.queue.some((entry) => entry.cue.agentId === 'verifier-b')
  }

  private setAgent(agentId: MapAgentId, update: Partial<Omit<AnimationAgentState, 'agentId'>>): void {
    this.agents = this.agents.map((agent) => agent.agentId === agentId ? { ...agent, ...update } : agent)
  }

  private emit(): void {
    const state = this.getState()
    this.listeners.forEach((listener) => listener(state))
  }
}
