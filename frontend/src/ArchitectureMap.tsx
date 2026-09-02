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
  MAP_TRANSFER_ROUTES,
  MAP_WIDTH,
  STAGING_DOCK,
  STAGING_SLOTS,
  type MapRoom,
} from './map-layout'
import {
  AnimationDirector,
  MAP_MOVEMENT_UNITS_PER_SECOND,
  RECORDED_REPLAY_MOVEMENT_UNITS_PER_SECOND,
  type AnimationAgentState,
  type AnimationDirectorState,
  type CardinalDirection,
} from './animation-director'
import { isMotionCue, type MapCue } from './map-cues'
import { ReplayAudioController } from './replay-audio'
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

function routeForActiveId(routeId: string | null) {
  if (!routeId) return null
  return MAP_ROUTES.find((candidate) => candidate.id === routeId)
    ?? MAP_TRANSFER_ROUTES.find((candidate) => candidate.id === routeId)
    ?? null
}

function motionSegment(
  agent: AnimationAgentState,
  cue: MapCue | null,
  activeRouteId: string | null,
  movementUnitsPerSecond: number,
) {
  if (cue === null || !isMotionCue(cue) || cue.agentId !== agent.agentId || (agent.phase !== 'walk' && agent.phase !== 'return')) return null
  const route = routeForActiveId(activeRouteId)
  if (!route) return null
  const points = agent.phase === 'walk' ? route.waypoints : [...route.waypoints].reverse()
  const index = points.findIndex((point) => samePoint(point, agent))
  if (index < 0 || index >= points.length - 1) return null
  const target = points[index + 1]
  const durationMs = (Math.abs(target.x - agent.x) + Math.abs(target.y - agent.y)) / movementUnitsPerSecond * 1000
  return { target, durationMs }
}

function frameName(agent: AnimationAgentState): SpriteFrameName {
  const stride = agent.phase === 'return' ? '1' : '0'
  return `${agent.direction}${stride}` as SpriteFrameName
}

function AnimatedAgent({
  agent,
  cue,
  activeRouteId,
  movementUnitsPerSecond,
  reducedMotion,
}: {
  agent: AnimationAgentState
  cue: MapCue | null
  activeRouteId: string | null
  movementUnitsPerSecond: number
  reducedMotion: boolean
}) {
  const manifest = AGENT_SPRITE_MANIFEST[agent.agentId]
  const frame = spriteFrame(agent.agentId, frameName(agent))
  const movement = reducedMotion ? null : motionSegment(agent, cue, activeRouteId, movementUnitsPerSecond)
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

type ToolAction = Exclude<MapCue['actionId'], 'none'>

function isToolAction(actionId: MapCue['actionId']): actionId is ToolAction {
  return actionId === 'scan' || actionId === 'probe' || actionId === 'pickaxe' || actionId === 'beam'
}

function toolTransform(direction: CardinalDirection): string {
  switch (direction) {
    case 'right': return 'rotate(90 32 30)'
    case 'down': return 'rotate(180 32 30)'
    case 'left': return 'rotate(270 32 30)'
    case 'up': return 'rotate(0 32 30)'
  }
}

function ToolEffect({
  agent,
  cue,
  cycleIndex,
  reducedMotion,
}: {
  agent: AnimationAgentState
  cue: MapCue | null
  cycleIndex: number | null
  reducedMotion: boolean
}) {
  if (!cue || !isMotionCue(cue) || cue.agentId !== agent.agentId || !isToolAction(cue.actionId)) return null
  if (agent.phase !== 'interact' && agent.phase !== 'acknowledge') return null
  const activeCycle = cycleIndex !== null
  const effectKey = `${cue.agentId}-${cue.roomId}-${cue.actionId}-${cycleIndex ?? 'acknowledge'}`
  const effectClass = `architecture-tool-effect architecture-tool-${cue.actionId}${activeCycle && !reducedMotion ? ' is-cycling' : ''}`
  const common = {
    className: effectClass,
    'data-tool-effect': cue.actionId,
    'data-effect-cycle': activeCycle ? String(cycleIndex) : 'acknowledge',
    'data-effect-key': effectKey,
  }
  return <g transform={`translate(${agent.x} ${agent.y})`} aria-hidden="true" {...common}>
    <svg key={effectKey} className="architecture-tool-viewport" x="-32" y="-28" width="64" height="56" viewBox="0 0 64 56" overflow="hidden">
      <g transform={toolTransform(agent.direction)}>
        {cue.actionId === 'scan' && <>
          <circle className="architecture-tool-body" cx="32" cy="28" r="4" />
          <path className="architecture-tool-scan-line" d="M32 23V8" />
          <path className="architecture-tool-scan-arc" d="M24 15a11 11 0 0 1 16 0" />
          <path className="architecture-tool-scan-arc architecture-tool-scan-arc-wide" d="M18 10a20 20 0 0 1 28 0" />
        </>}
        {cue.actionId === 'probe' && <>
          <path className="architecture-tool-probe-wand" d="M32 28V9" />
          <rect className="architecture-tool-probe-handle" x="28.5" y="24" width="7" height="8" rx="1" />
          <path className="architecture-tool-probe-spark" d="M32 5l2 3-2 3-2-3z" />
        </>}
        {cue.actionId === 'pickaxe' && <>
          <path className="architecture-tool-pickaxe-handle" d="M32 30L22 10" />
          <path className="architecture-tool-pickaxe-head" d="M15 12c6-5 14-5 20 0M17 14l5 3" />
          <path className="architecture-tool-impact" d="M32 6l2 2 3-1-1 3 2 2-3 1-1 3-2-2-3 1 1-3-2-2 3-1z" />
        </>}
        {cue.actionId === 'beam' && <>
          <rect className="architecture-tool-beam-device" x="28" y="23" width="8" height="10" rx="1" />
          <path className="architecture-tool-beam-line" d="M32 23V5" />
          <path className="architecture-tool-beam-cap" d="M27 7h10" />
        </>}
      </g>
    </svg>
  </g>
}

function animationAnnouncement(animation: AnimationDirectorState): string {
  const cue = animation.currentCue
  if (cue === null || !isMotionCue(cue)) return animation.statusText
  const agent = animation.agents.find((candidate) => candidate.agentId === cue.agentId)
  const room = MAP_ROOMS.find((candidate) => candidate.id === cue.roomId)
  const phase = agent?.phase ?? 'docked'
  const action = cue.actionId === 'scan' ? 'scan' : cue.actionId === 'probe' ? 'probe' : cue.actionId === 'pickaxe' ? 'pickaxe review' : cue.actionId === 'beam' ? 'beam review' : 'inspection'
  const cycle = animation.currentCycleIndex ? ` Cycle ${animation.currentCycleIndex} of ${cue.cycles}.` : ''
  return `${AGENT_SPRITE_MANIFEST[cue.agentId].label}, ${room?.label ?? 'fixed room'}, ${phase}, ${action}.${cycle} ${cue.caption}`
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

function useMapAnimation(
  events: readonly PresentationEvent[],
  generation: number,
  movementUnitsPerSecond: number,
): AnimationDirectorState {
  const directorRef = useRef<AnimationDirector | null>(null)
  if (directorRef.current === null) directorRef.current = new AnimationDirector({ reducedMotion: getReducedMotion(), movementUnitsPerSecond })
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
        if (cleanupVersion.current === version) director.reset()
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

interface AudioMarkers {
  walking: string | null
  tool: string | null
  terminal: boolean
  terminalSequences: Set<number>
}

function useReplayAudio(
  events: readonly PresentationEvent[],
  animation: AnimationDirectorState,
  generation: number,
  soundEnabled: boolean,
  recordedReplay: boolean,
): void {
  const controllerRef = useRef<ReplayAudioController | null>(null)
  if (controllerRef.current === null) controllerRef.current = new ReplayAudioController({ enabled: soundEnabled })
  const controller = controllerRef.current
  const markersRef = useRef<AudioMarkers>({ walking: null, tool: null, terminal: false, terminalSequences: new Set() })
  const audioCleanupVersion = useRef(0)

  useEffect(() => {
    controller.reset()
    controller.setEnabled(soundEnabled)
    markersRef.current = { walking: null, tool: null, terminal: false, terminalSequences: new Set() }
    if (recordedReplay && generation > 0) controller.armReplay()
  }, [controller, generation, recordedReplay])

  useEffect(() => {
    controller.setEnabled(soundEnabled)
  }, [controller, soundEnabled])

  useEffect(() => {
    const version = ++audioCleanupVersion.current
    return () => {
      globalThis.queueMicrotask(() => {
        if (audioCleanupVersion.current !== version) return
        controller.reset()
      })
    }
  }, [controller])

  useEffect(() => {
    if (!recordedReplay || generation === 0 || !controller.isArmed() || markersRef.current.terminal) return
    const moving = animation.agents.find((agent) => agent.phase === 'walk' || agent.phase === 'return')
    const walking = moving ? `${moving.agentId}:${moving.phase}:${moving.x}:${moving.y}:${moving.direction}:${animation.activeRouteId ?? ''}` : null
    if (walking && walking !== markersRef.current.walking) controller.playCue('footsteps')
    markersRef.current.walking = walking

    const cue = animation.currentCue
    const tool = cue && isMotionCue(cue) && isToolAction(cue.actionId) && animation.currentCycleIndex !== null
      ? `${cue.agentId}:${cue.roomId}:${cue.actionId}:${animation.currentCycleIndex}`
      : null
    if (tool && tool !== markersRef.current.tool && cue && isToolAction(cue.actionId)) controller.playCue(cue.actionId)
    markersRef.current.tool = tool
  }, [animation, controller, generation, recordedReplay])

  useEffect(() => {
    if (!recordedReplay || generation === 0 || !controller.isArmed()) return
    for (const event of events) {
      if (markersRef.current.terminalSequences.has(event.sequence)) continue
      markersRef.current.terminalSequences.add(event.sequence)
      if (event.type === 'consensus.completed' && event.state === 'completed') controller.playCue('consensus')
      if (event.type === 'session.failed' && event.state === 'failed') {
        markersRef.current.terminal = true
        controller.playCue('failure')
      }
      if (event.type === 'session.completed' && event.state === 'completed') {
        markersRef.current.terminal = true
        controller.stop()
      }
    }
  }, [controller, events, generation, recordedReplay])
}

export function ArchitectureMap({
  events,
  generation = 0,
  soundEnabled = true,
  recordedReplay = false,
  onAnimationActiveChange,
}: {
  events: readonly PresentationEvent[]
  generation?: number
  soundEnabled?: boolean
  recordedReplay?: boolean
  onAnimationActiveChange?: (active: boolean) => void
}) {
  const map = deriveArchitectureMap(events)
  const relatedNodes = map.relation?.nodeIds ?? []
  const animation = useMapAnimation(
    events,
    generation,
    recordedReplay ? RECORDED_REPLAY_MOVEMENT_UNITS_PER_SECOND : MAP_MOVEMENT_UNITS_PER_SECOND,
  )
  useReplayAudio(events, animation, generation, soundEnabled, recordedReplay)
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
            {animation.agents.map((agent) => <AnimatedAgent
              key={agent.agentId}
              agent={agent}
              cue={animation.currentCue}
              activeRouteId={animation.activeRouteId}
              movementUnitsPerSecond={animation.movementUnitsPerSecond}
              reducedMotion={animation.reducedMotion}
            />)}
            {animation.agents.map((agent) => <ToolEffect
              key={`tool-${agent.agentId}`}
              agent={agent}
              cue={animation.currentCue}
              cycleIndex={animation.currentCycleIndex}
              reducedMotion={animation.reducedMotion}
            />)}
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
    </section>
  )
}
