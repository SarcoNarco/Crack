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
  type MapAgentId,
  type MapRoom,
} from './map-layout'
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

function AgentConcept({ agentId, label, x, y }: { agentId: MapAgentId; label: string; x: number; y: number }) {
  const spritePaths: Record<MapAgentId, string> = {
    mapper: '/map/agents/mapper.png',
    'authorization-tester': '/map/agents/authorization-tester.png',
    'verifier-a': '/map/agents/verifier-a.png',
    'verifier-b': '/map/agents/verifier-b.png',
  }
  const displayLabel = agentId === 'authorization-tester' ? 'AUTH TESTER' : label.toUpperCase()
  return <g data-agent-id={agentId} data-agent-concept="static" className="architecture-agent-concept" transform={`translate(${x} ${y})`} aria-hidden="true">
    <text className="architecture-agent-label" x="0" y="-16" textAnchor="middle">{displayLabel}</text>
    <ellipse className="architecture-agent-shadow" cx="0" cy="13" rx="13" ry="3" />
    <image className="architecture-agent-sprite" href={spritePaths[agentId]} x="-16" y="-16" width="32" height="32" preserveAspectRatio="xMidYMid meet" />
  </g>
}

export function ArchitectureMap({ events }: { events: readonly PresentationEvent[] }) {
  const map = deriveArchitectureMap(events)
  const relatedNodes = map.relation?.nodeIds ?? []
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
          <title id="architecture-svg-title">Static school portal operations floor</title>
          <desc id="architecture-svg-description">Six canonical school-portal rooms, nine fixed orthogonal corridors, and four static staged agent concepts named Mapper, Authorization Tester, Verifier A, and Verifier B. Highlighting only relates latest received presentation event to rooms; it does not prove an attack result.</desc>
          <defs><pattern id="architecture-floor-grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" className="architecture-floor-grid" /></pattern></defs>
          <image className="architecture-environment-image" href="/map/crack-operations-floor.png" x="0" y="0" width={MAP_WIDTH} height={MAP_HEIGHT} preserveAspectRatio="xMidYMid slice" aria-hidden="true" />
          <rect className="architecture-floor-base" x="0" y="0" width={MAP_WIDTH} height={MAP_HEIGHT} />
          <rect className="architecture-floor-grid-fill" x="0" y="0" width={MAP_WIDTH} height={MAP_HEIGHT} fill="url(#architecture-floor-grid)" />
          <g className="architecture-corridor-layer" aria-hidden="true">
            {MAP_ROUTES.map((route) => <polyline key={route.id} data-corridor-id={route.id} className={`architecture-corridor${hasNode(relatedNodes, route.roomId) ? ' is-related' : ''}`} points={routePoints(route.waypoints)} />)}
          </g>
          <g className="architecture-room-layer">
            {MAP_ROOMS.map((room) => <g key={room.id} data-node-id={room.id} data-room-id={room.id} className={`architecture-room${hasNode(relatedNodes, room.id) ? ' is-related' : ''}`}>
              <title>{room.label}: {ARCHITECTURE_GRAPH.nodes.find((node) => node.id === room.id)!.description}</title><RoomEquipment room={room} />
            </g>)}
          </g>
          <g className="architecture-staging-layer" aria-hidden="true">
            <rect className="architecture-staging-dock" x={STAGING_DOCK.x} y={STAGING_DOCK.y} width={STAGING_DOCK.width} height={STAGING_DOCK.height} rx="6" />
            <text className="architecture-staging-label" x={STAGING_DOCK.x + STAGING_DOCK.width / 2} y={STAGING_DOCK.y - 9} textAnchor="middle">STAGING DOCK</text>
            {STAGING_SLOTS.map((slot) => <g key={slot.agentId}><rect className="architecture-staging-slot" x={slot.bounds.x} y={slot.bounds.y} width={slot.bounds.width} height={slot.bounds.height} rx="4" /><AgentConcept agentId={slot.agentId} label={slot.label} x={slot.dockPoint.x} y={slot.dockPoint.y} /></g>)}
          </g>
        </svg>
        <p className="architecture-pan-hint">Swipe or use Shift + mouse wheel to view the full operations floor.</p>
        </div>
        <aside className="architecture-context" aria-live="polite" aria-atomic="true">
          {map.event && map.relation ? <><p className="kicker">Latest received event</p><h3>{map.event.headline}</h3><dl>
            <div><dt>Actor</dt><dd>{map.relation.actor}</dd></div>
            <div><dt>Presentation state</dt><dd><span className={`architecture-state state-${map.event.state}`}>{map.event.state}</span></dd></div>
            <div><dt>Presentation marker</dt><dd>Reserved for later choreography <span className="architecture-static-tag">static presentation</span></dd></div>
            <div><dt>Related components</dt><dd>{relatedNodes.length ? relatedNodes.map((id) => ARCHITECTURE_GRAPH.nodes.find((node) => node.id === id)!.label).join(' · ') : 'Outside this static target map'}</dd></div>
          </dl></> : <><p className="kicker">Waiting</p><h3>No presentation event received</h3><p>No target components are currently related. Floor remains a static reference.</p></>}
        </aside>
      </div>
      <p className="architecture-note">Rooms and corridors mirror fixed Sprint 18 canonical portal relationships. Floor is watch-only and static in Sprint 23; verified findings remain code-owned consensus. It does not load, revalidate, or run an imported target snapshot.</p>
    </section>
  )
}
