import { useEffect, useRef, useState } from 'react'
import {
  ARCHITECTURE_GRAPH,
  deriveArchitectureMap,
  type ArchitectureNodeId,
} from './architecture'
import {
  MAP_HEIGHT,
  MAP_ROOMS,
  MAP_ROUTES,
  MAP_WIDTH,
  STAGING_DOCK,
  STAGING_SLOTS,
  type MapRoom,
} from './map-layout'
import { AnimationDirector, MAP_MOVEMENT_UNITS_PER_SECOND, type AnimationAgentState, type AnimationDirectorState } from './animation-director'
import { isMotionCue, type MapCue } from './map-cues'
import { AGENT_SPRITE_MANIFEST, spriteFrame, type SpriteFrameName } from './sprite-manifest'
import type { PresentationEvent } from './types'

function hasNode(nodeIds: readonly ArchitectureNodeId[], nodeId: ArchitectureNodeId): boolean {
  return nodeIds.includes(nodeId)
}

function routePoints(points: readonly { x: number; y: number }[]): string {
  return points.map((point) => `${point.x},${point.y}`).join(' ')
}

const SHORT_ROOM_LABELS: Record<ArchitectureNodeId, string> = {
  'browser-portal': 'Browser',
  'fastapi-api': 'FastAPI',
  'grade-lifecycle': 'Grade lab',
  'role-authentication': 'Role / Auth',
  'sqlite-persistence': 'SQLite',
  submissions: 'Submissions',
}

function RoomEquipment({ room }: { room: MapRoom }) {
  const { x, y, width, height } = room.bounds
  const centerX = x + width / 2
  return <>
    <rect className="architecture-room-shell" x={x} y={y} width={width} height={height} rx="8" />
    <rect className="architecture-room-label-plate" x={centerX - Math.min(width - 24, room.label.length * 7.2) / 2} y={y + 7} width={Math.min(width - 24, room.label.length * 7.2)} height="23" rx="3" />
    <text aria-hidden="true" className="architecture-room-label architecture-room-label-long" x={centerX} y={y + 22} textAnchor="middle">{room.label}</text>
    <text aria-hidden="true" className="architecture-room-label architecture-room-label-short" x={centerX} y={y + 22} textAnchor="middle">{SHORT_ROOM_LABELS[room.id]}</text>
    <circle className="architecture-interaction-point" cx={room.interactionPoint.x} cy={room.interactionPoint.y} r="4" />
  </>
}

function getReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function samePoint(left: { x: number; y: number }, right: { x: number; y: number }): boolean {
  return left.x === right.x && left.y === right.y
}

function motionSegment(agent: AnimationAgentState, cue: MapCue | null) {
  if (cue === null || !isMotionCue(cue) || cue.agentId !== agent.agentId || (agent.phase !== 'walk' && agent.phase !== 'return')) return null
  const route = MAP_ROUTES.find((candidate) => candidate.id === cue.routeId)
  if (!route) return null
  const points = agent.phase === 'walk' ? route.waypoints : [...route.waypoints].reverse()
  const index = points.findIndex((point) => samePoint(point, agent))
  if (index < 0 || index >= points.length - 1) return null
  const target = points[index + 1]
  const durationMs = (Math.abs(target.x - agent.x) + Math.abs(target.y - agent.y)) / MAP_MOVEMENT_UNITS_PER_SECOND * 1000
  return { target, durationMs }
}

function frameName(agent: AnimationAgentState): SpriteFrameName {
  const stride = agent.phase === 'return' ? '1' : '0'
  return `${agent.direction}${stride}` as SpriteFrameName
}

function AnimatedAgent({ agent, cue, reducedMotion }: { agent: AnimationAgentState; cue: MapCue | null; reducedMotion: boolean }) {
  const manifest = AGENT_SPRITE_MANIFEST[agent.agentId]
  const frame = spriteFrame(agent.agentId, frameName(agent))
  const movement = reducedMotion ? null : motionSegment(agent, cue)
  const alternateFrame = spriteFrame(agent.agentId, `${agent.direction}${frame.name.endsWith('0') ? '1' : '0'}` as SpriteFrameName)
  return <g
    data-agent-id={agent.agentId}
    data-agent-state={agent.phase}
    data-agent-direction={agent.direction}
    data-agent-frame={frame.name}
    className={`architecture-agent architecture-agent-${agent.phase}`}
    aria-hidden="true"
  >
    <g transform={`translate(${agent.x} ${agent.y})`}>
      {movement ? <animateTransform
        attributeName="transform"
        type="translate"
        from="0 0"
        to={`${movement.target.x - agent.x} ${movement.target.y - agent.y}`}
        dur={`${movement.durationMs}ms`}
        fill="freeze"
        additive="sum"
      /> : null}
      <text className="architecture-agent-label" x="0" y="-22" textAnchor="middle">{manifest.label}</text>
      <ellipse className="architecture-agent-shadow" cx="0" cy="13" rx="13" ry="3" />
      <svg className="architecture-agent-viewport" x="-16" y="-16" width="32" height="32" viewBox="0 0 32 32" overflow="hidden" aria-hidden="true">
        <image
          id={`architecture-agent-sheet-${agent.agentId}`}
          className="architecture-agent-sprite"
          href={manifest.sheet}
          x={-frame.x}
          y="0"
          width="256"
          height="32"
          preserveAspectRatio="none"
        />
        {movement ? <animate href={`#architecture-agent-sheet-${agent.agentId}`} attributeName="x" values={`${-frame.x};${-alternateFrame.x};${-frame.x}`} dur="160ms" repeatDur={`${movement.durationMs}ms`} calcMode="discrete" /> : null}
      </svg>
    </g>
  </g>
}

function animationAnnouncement(animation: AnimationDirectorState): string {
  const cue = animation.currentCue
  if (cue === null || !isMotionCue(cue)) return animation.statusText
  const agent = animation.agents.find((candidate) => candidate.agentId === cue.agentId)
  const room = MAP_ROOMS.find((candidate) => candidate.id === cue.roomId)
  const phase = agent?.phase ?? 'docked'
  const action = cue.actionId === 'scan' ? 'scan' : cue.actionId === 'probe' ? 'probe' : 'inspection'
  return `${AGENT_SPRITE_MANIFEST[cue.agentId].label}, ${room?.label ?? 'fixed room'}, ${phase}, ${action}. ${cue.caption}`
}

interface EventFeedState {
  initialized: boolean
  generation: number
  sessionId: string | null
  armedFromEmpty: boolean
  seen: Set<number>
  visibleLength: number
  visibleLastSequence: number
}

function useMapAnimation(events: readonly PresentationEvent[], generation: number): AnimationDirectorState {
  const directorRef = useRef<AnimationDirector | null>(null)
  if (directorRef.current === null) directorRef.current = new AnimationDirector({ reducedMotion: getReducedMotion() })
  const director = directorRef.current
  const [animationState, setAnimationState] = useState<AnimationDirectorState>(() => director.getState())
  const feedRef = useRef<EventFeedState>({
    initialized: false,
    generation,
    sessionId: null,
    armedFromEmpty: false,
    seen: new Set(),
    visibleLength: 0,
    visibleLastSequence: Number.NEGATIVE_INFINITY,
  })
  const cleanupVersion = useRef(0)

  useEffect(() => {
    const version = ++cleanupVersion.current
    const unsubscribe = director.subscribe(setAnimationState)
    return () => {
      unsubscribe()
      globalThis.queueMicrotask(() => {
        if (cleanupVersion.current === version) director.destroy()
      })
    }
  }, [director])

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => director.setReducedMotion(media.matches)
    update()
    media.addEventListener?.('change', update)
    return () => media.removeEventListener?.('change', update)
  }, [director])

  useEffect(() => {
    const feed = feedRef.current
    if (feed.generation !== generation) {
      director.reset()
      feed.generation = generation
      feed.initialized = true
      feed.sessionId = null
      feed.armedFromEmpty = true
      feed.seen.clear()
      feed.visibleLength = 0
      feed.visibleLastSequence = Number.NEGATIVE_INFINITY
    }
    if (events.length === 0) {
      if (feed.armedFromEmpty) director.reset()
      feed.initialized = true
      feed.sessionId = null
      feed.seen.clear()
      feed.visibleLength = 0
      feed.visibleLastSequence = Number.NEGATIVE_INFINITY
      return
    }
    const sessionId = events[0].session_id
    const visibleLastSequence = events.at(-1)!.sequence
    if (!feed.initialized) {
      feed.initialized = true
      feed.sessionId = sessionId
      for (const event of events) feed.seen.add(event.sequence)
      feed.visibleLength = events.length
      feed.visibleLastSequence = visibleLastSequence
      return
    }
    const sessionChanged = sessionId !== feed.sessionId
    const replayRewind = !sessionChanged
      && events.length < feed.visibleLength
      && visibleLastSequence < feed.visibleLastSequence
    if (sessionChanged || replayRewind) {
      director.reset()
      feed.seen.clear()
      feed.sessionId = sessionId
      if (sessionChanged && !feed.armedFromEmpty) {
        for (const event of events) feed.seen.add(event.sequence)
        feed.visibleLength = events.length
        feed.visibleLastSequence = visibleLastSequence
        return
      }
      feed.armedFromEmpty = true
    }
    const incoming = events.filter((event) => !feed.seen.has(event.sequence))
    for (const event of incoming) feed.seen.add(event.sequence)
    if (incoming.length) director.enqueue(incoming)
    feed.visibleLength = events.length
    feed.visibleLastSequence = visibleLastSequence
  }, [director, events, generation])

  return animationState
}

export function ArchitectureMap({
  events,
  generation = 0,
  onAnimationActiveChange,
}: {
  events: readonly PresentationEvent[]
  generation?: number
  onAnimationActiveChange?: (active: boolean) => void
}) {
  const map = deriveArchitectureMap(events)
  const relatedNodes = map.relation?.nodeIds ?? []
  const animation = useMapAnimation(events, generation)
  const highlightedNodes = animation.currentCue && isMotionCue(animation.currentCue)
    ? [animation.currentCue.roomId]
    : relatedNodes
  useEffect(() => {
    onAnimationActiveChange?.(animation.active)
  }, [animation.active, onAnimationActiveChange])
  return (
    <section className="architecture-section" aria-labelledby="architecture-heading">
      <div className="section-heading">
        <div>
          <p className="kicker">Static target reference</p>
          <h2 id="architecture-heading">Target architecture floor</h2>
          <p>Watch-only floor view. Latest accepted event highlights related canonical rooms; it does not show a process location, runtime binding, or attack result.</p>
        </div>
      </div>
      <div className="architecture-layout">
        <div className="architecture-map-viewport" role="region" aria-label="Scrollable operations floor" tabIndex={0}>
        <svg className="architecture-map" viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} role="img" aria-labelledby="architecture-svg-title architecture-svg-description">
          <title id="architecture-svg-title">School portal operations floor</title>
          <desc id="architecture-svg-description">Six canonical school-portal rooms, nine fixed orthogonal corridors, and four labeled staged agents named Mapper, Authorization Tester, Verifier A, and Verifier B. Accepted events may present one finite journey at a time; this remains a watch-only relationship view and does not prove an attack result.</desc>
          <defs><pattern id="architecture-floor-grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" className="architecture-floor-grid" /></pattern></defs>
          <image className="architecture-environment-image" href="/map/crack-operations-floor.png" x="0" y="0" width={MAP_WIDTH} height={MAP_HEIGHT} preserveAspectRatio="xMidYMid slice" aria-hidden="true" />
          <rect className="architecture-floor-base" x="0" y="0" width={MAP_WIDTH} height={MAP_HEIGHT} />
          <rect className="architecture-floor-grid-fill" x="0" y="0" width={MAP_WIDTH} height={MAP_HEIGHT} fill="url(#architecture-floor-grid)" />
          <g className="architecture-corridor-layer" aria-hidden="true">
            {MAP_ROUTES.map((route) => <polyline key={route.id} data-corridor-id={route.id} className={`architecture-corridor${hasNode(highlightedNodes, route.roomId) ? ' is-related' : ''}`} points={routePoints(route.waypoints)} />)}
          </g>
          <g className="architecture-room-layer">
            {MAP_ROOMS.map((room) => <g key={room.id} data-node-id={room.id} data-room-id={room.id} className={`architecture-room${hasNode(highlightedNodes, room.id) ? ' is-related' : ''}`}>
              <title>{room.label}: {ARCHITECTURE_GRAPH.nodes.find((node) => node.id === room.id)!.description}</title><RoomEquipment room={room} />
            </g>)}
          </g>
          <g className="architecture-staging-layer" aria-hidden="true">
            <rect className="architecture-staging-dock" x={STAGING_DOCK.x} y={STAGING_DOCK.y} width={STAGING_DOCK.width} height={STAGING_DOCK.height} rx="6" />
            <text className="architecture-staging-label" x={STAGING_DOCK.x + STAGING_DOCK.width / 2} y={STAGING_DOCK.y - 9} textAnchor="middle">STAGING DOCK</text>
            {STAGING_SLOTS.map((slot) => <rect key={slot.agentId} className="architecture-staging-slot" x={slot.bounds.x} y={slot.bounds.y} width={slot.bounds.width} height={slot.bounds.height} rx="4" />)}
          </g>
          <g className="architecture-agent-layer" aria-label="Agent staging and finite journey presentation">
            {animation.agents.map((agent) => <AnimatedAgent key={agent.agentId} agent={agent} cue={animation.currentCue} reducedMotion={animation.reducedMotion} />)}
          </g>
        </svg>
        <p className="architecture-pan-hint">Swipe or use Shift + mouse wheel to view the full operations floor.</p>
        </div>
        <aside className="architecture-context">
          {map.event && map.relation ? <><p className="kicker">Latest received event</p><h3>{map.event.headline}</h3><dl>
            <div><dt>Actor</dt><dd>{map.relation.actor}</dd></div>
            <div><dt>Presentation state</dt><dd><span className={`architecture-state state-${map.event.state}`}>{map.event.state}</span></dd></div>
            <div><dt>Character presentation</dt><dd>{animation.currentCue ? 'One finite, safe journey is presenting' : 'All agents are staged'} <span className="architecture-static-tag">watch-only</span></dd></div>
            <div><dt>Related components</dt><dd>{relatedNodes.length ? relatedNodes.map((id) => ARCHITECTURE_GRAPH.nodes.find((node) => node.id === id)!.label).join(' · ') : 'Outside this static target map'}</dd></div>
          </dl></> : <><p className="kicker">Waiting</p><h3>No presentation event received</h3><p>No target components are currently related. Floor remains a static reference.</p></>}
        </aside>
      </div>
      <p className="architecture-animation-status" aria-live="polite" aria-atomic="true">{animationAnnouncement(animation)}</p>
      <p className="architecture-note">Rooms and corridors mirror fixed Sprint 18 canonical portal relationships. Agent journeys present accepted events only; verified findings remain code-owned consensus. This does not load, revalidate, or run an imported target snapshot.</p>
    </section>
  )
}
