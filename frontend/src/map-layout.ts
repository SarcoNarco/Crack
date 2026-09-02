import { ARCHITECTURE_NODE_IDS, type ArchitectureNodeId } from './architecture'

export const MAP_WIDTH = 960
export const MAP_HEIGHT = 540
export const MAP_EDGE_INSET = 32

export interface MapPoint {
  readonly x: number
  readonly y: number
}

export interface MapBounds {
  readonly x: number
  readonly y: number
  readonly width: number
  readonly height: number
}

export interface MapRoom {
  readonly id: ArchitectureNodeId
  readonly label: string
  readonly bounds: MapBounds
  readonly interactionPoint: MapPoint
}

export const MAP_ROOM_IDS = ARCHITECTURE_NODE_IDS

export const MAP_ROOMS: readonly MapRoom[] = [
  { id: 'browser-portal', label: 'Browser portal', bounds: { x: 56, y: 52, width: 230, height: 126 }, interactionPoint: { x: 170, y: 204 } },
  { id: 'fastapi-api', label: 'FastAPI API', bounds: { x: 54, y: 278, width: 240, height: 128 }, interactionPoint: { x: 320, y: 342 } },
  { id: 'grade-lifecycle', label: 'Grade lifecycle', bounds: { x: 656, y: 276, width: 222, height: 128 }, interactionPoint: { x: 628, y: 340 } },
  { id: 'role-authentication', label: 'Role and authentication', bounds: { x: 360, y: 48, width: 230, height: 130 }, interactionPoint: { x: 476, y: 204 } },
  { id: 'sqlite-persistence', label: 'SQLite persistence', bounds: { x: 738, y: 432, width: 168, height: 72 }, interactionPoint: { x: 822, y: 410 } },
  { id: 'submissions', label: 'Submissions', bounds: { x: 700, y: 52, width: 204, height: 126 }, interactionPoint: { x: 814, y: 204 } },
] as const

export const MAP_AGENT_IDS = ['mapper', 'authorization-tester', 'verifier-a', 'verifier-b'] as const
export type MapAgentId = typeof MAP_AGENT_IDS[number]

export interface StagingSlot {
  readonly agentId: MapAgentId
  readonly label: string
  readonly bounds: MapBounds
  readonly dockPoint: MapPoint
}

export const STAGING_DOCK: MapBounds = { x: 198, y: 448, width: 520, height: 60 }

export const STAGING_SLOTS: readonly StagingSlot[] = [
  { agentId: 'mapper', label: 'Mapper', bounds: { x: 216, y: 458, width: 110, height: 40 }, dockPoint: { x: 271, y: 478 } },
  { agentId: 'authorization-tester', label: 'Authorization Tester', bounds: { x: 346, y: 458, width: 110, height: 40 }, dockPoint: { x: 401, y: 478 } },
  { agentId: 'verifier-a', label: 'Verifier A', bounds: { x: 476, y: 458, width: 110, height: 40 }, dockPoint: { x: 531, y: 478 } },
  { agentId: 'verifier-b', label: 'Verifier B', bounds: { x: 606, y: 458, width: 110, height: 40 }, dockPoint: { x: 661, y: 478 } },
] as const

export interface MapWaypointRoute {
  readonly id: string
  readonly waypoints: readonly MapPoint[]
}

export interface MapRoute extends MapWaypointRoute {
  readonly agentId: MapAgentId
  readonly roomId: ArchitectureNodeId
}

/**
 * Fixed room-to-room corridors used only when adjacent safe cues keep the
 * same agent on one journey. They never accept event-provided coordinates.
 */
export interface MapTransferRoute extends MapWaypointRoute {
  readonly fromRoomId: ArchitectureNodeId
  readonly toRoomId: ArchitectureNodeId
  readonly waypoints: readonly MapPoint[]
}

const mapperDock = STAGING_SLOTS[0].dockPoint
const authorizationDock = STAGING_SLOTS[1].dockPoint
const verifierADock = STAGING_SLOTS[2].dockPoint
const verifierBDock = STAGING_SLOTS[3].dockPoint

/* Every segment belongs to an authored corridor. Shared geometry is intentional. */
export const MAP_ROUTES: readonly MapRoute[] = [
  { id: 'mapper-to-browser-portal', agentId: 'mapper', roomId: 'browser-portal', waypoints: [mapperDock, { x: 320, y: 478 }, { x: 320, y: 244 }, { x: 170, y: 244 }, { x: 170, y: 204 }] },
  { id: 'mapper-to-fastapi-api', agentId: 'mapper', roomId: 'fastapi-api', waypoints: [mapperDock, { x: 320, y: 478 }, { x: 320, y: 342 }] },
  { id: 'authorization-tester-to-role-authentication', agentId: 'authorization-tester', roomId: 'role-authentication', waypoints: [authorizationDock, { x: 401, y: 244 }, { x: 476, y: 244 }, { x: 476, y: 204 }] },
  { id: 'authorization-tester-to-submissions', agentId: 'authorization-tester', roomId: 'submissions', waypoints: [authorizationDock, { x: 401, y: 244 }, { x: 814, y: 244 }, { x: 814, y: 204 }] },
  { id: 'authorization-tester-to-grade-lifecycle', agentId: 'authorization-tester', roomId: 'grade-lifecycle', waypoints: [authorizationDock, { x: 401, y: 244 }, { x: 628, y: 244 }, { x: 628, y: 340 }] },
  { id: 'verifier-a-to-submissions', agentId: 'verifier-a', roomId: 'submissions', waypoints: [verifierADock, { x: 531, y: 244 }, { x: 814, y: 244 }, { x: 814, y: 204 }] },
  { id: 'verifier-a-to-grade-lifecycle', agentId: 'verifier-a', roomId: 'grade-lifecycle', waypoints: [verifierADock, { x: 531, y: 244 }, { x: 628, y: 244 }, { x: 628, y: 340 }] },
  { id: 'verifier-b-to-submissions', agentId: 'verifier-b', roomId: 'submissions', waypoints: [verifierBDock, { x: 628, y: 478 }, { x: 628, y: 244 }, { x: 814, y: 244 }, { x: 814, y: 204 }] },
  { id: 'verifier-b-to-grade-lifecycle', agentId: 'verifier-b', roomId: 'grade-lifecycle', waypoints: [verifierBDock, { x: 628, y: 478 }, { x: 628, y: 340 }] },
] as const

export const MAP_TRANSFER_ROUTES: readonly MapTransferRoute[] = [
  {
    id: 'submissions-to-grade-lifecycle',
    fromRoomId: 'submissions',
    toRoomId: 'grade-lifecycle',
    waypoints: [{ x: 814, y: 204 }, { x: 814, y: 244 }, { x: 628, y: 244 }, { x: 628, y: 340 }],
  },
  {
    id: 'grade-lifecycle-to-submissions',
    fromRoomId: 'grade-lifecycle',
    toRoomId: 'submissions',
    waypoints: [{ x: 628, y: 340 }, { x: 628, y: 244 }, { x: 814, y: 244 }, { x: 814, y: 204 }],
  },
] as const

export interface MapSegment {
  readonly start: MapPoint
  readonly end: MapPoint
}

const CORRIDOR_JUNCTIONS: readonly MapPoint[] = [
  { x: 170, y: 244 },
  { x: 320, y: 244 },
  { x: 320, y: 342 },
  { x: 320, y: 478 },
  { x: 401, y: 244 },
  { x: 476, y: 244 },
  { x: 531, y: 244 },
  { x: 628, y: 244 },
  { x: 628, y: 478 },
  { x: 814, y: 244 },
] as const

const CORRIDOR_SEGMENTS: readonly MapSegment[] = [
  { start: { x: 170, y: 244 }, end: { x: 814, y: 244 } },
  { start: { x: 170, y: 204 }, end: { x: 170, y: 244 } },
  { start: { x: 271, y: 478 }, end: { x: 320, y: 478 } },
  { start: { x: 320, y: 244 }, end: { x: 320, y: 478 } },
  { start: { x: 401, y: 244 }, end: { x: 401, y: 478 } },
  { start: { x: 476, y: 204 }, end: { x: 476, y: 244 } },
  { start: { x: 531, y: 244 }, end: { x: 531, y: 478 } },
  { start: { x: 628, y: 478 }, end: { x: 661, y: 478 } },
  { start: { x: 628, y: 244 }, end: { x: 628, y: 478 } },
  { start: { x: 814, y: 204 }, end: { x: 814, y: 244 } },
] as const

function within(value: number, first: number, second: number): boolean {
  return value >= Math.min(first, second) && value <= Math.max(first, second)
}

function pointsEqual(left: MapPoint, right: MapPoint): boolean {
  return left.x === right.x && left.y === right.y
}

function isPointOnSegment(point: MapPoint, segment: MapSegment): boolean {
  return segment.start.x === segment.end.x
    ? point.x === segment.start.x && within(point.y, segment.start.y, segment.end.y)
    : point.y === segment.start.y && within(point.x, segment.start.x, segment.end.x)
}

function isCorridorSegment(segment: MapSegment): boolean {
  return CORRIDOR_SEGMENTS.some((corridor) =>
    (corridor.start.x === corridor.end.x) === (segment.start.x === segment.end.x)
    && isPointOnSegment(segment.start, corridor)
    && isPointOnSegment(segment.end, corridor),
  )
}

function isCorridorJunction(point: MapPoint): boolean {
  return CORRIDOR_JUNCTIONS.some((junction) => pointsEqual(point, junction))
}

export function isPointInsideBounds(point: MapPoint, bounds: MapBounds): boolean {
  return point.x >= bounds.x
    && point.x <= bounds.x + bounds.width
    && point.y >= bounds.y
    && point.y <= bounds.y + bounds.height
}

export function isPointInsideMap(point: MapPoint): boolean {
  return point.x >= 0 && point.x <= MAP_WIDTH && point.y >= 0 && point.y <= MAP_HEIGHT
}

export function isBoundsInsideMap(bounds: MapBounds): boolean {
  return bounds.x >= MAP_EDGE_INSET
    && bounds.y >= MAP_EDGE_INSET
    && bounds.x + bounds.width <= MAP_WIDTH - MAP_EDGE_INSET
    && bounds.y + bounds.height <= MAP_HEIGHT - MAP_EDGE_INSET
}

export function routeSegments(route: MapWaypointRoute): readonly MapSegment[] {
  return route.waypoints.slice(1).map((end, index) => ({ start: route.waypoints[index], end }))
}

export function isCardinalRoute(route: MapWaypointRoute): boolean {
  return routeSegments(route).every(({ start, end }) => (start.x === end.x) !== (start.y === end.y))
}

export interface RouteCrossing {
  readonly firstRouteId: string
  readonly secondRouteId: string
  readonly point: MapPoint
}

function crossingPoint(first: MapSegment, second: MapSegment): MapPoint | null {
  const firstVertical = first.start.x === first.end.x
  const secondVertical = second.start.x === second.end.x
  if (firstVertical === secondVertical) return null
  const vertical = firstVertical ? first : second
  const horizontal = firstVertical ? second : first
  const point = { x: vertical.start.x, y: horizontal.start.y }
  return isPointOnSegment(point, vertical) && isPointOnSegment(point, horizontal) ? point : null
}

function collinearOverlapPoint(first: MapSegment, second: MapSegment): MapPoint | null {
  const firstVertical = first.start.x === first.end.x
  const secondVertical = second.start.x === second.end.x
  if (firstVertical !== secondVertical) return null
  if (firstVertical) {
    if (first.start.x !== second.start.x) return null
    const start = Math.max(Math.min(first.start.y, first.end.y), Math.min(second.start.y, second.end.y))
    const end = Math.min(Math.max(first.start.y, first.end.y), Math.max(second.start.y, second.end.y))
    return start <= end ? { x: first.start.x, y: start } : null
  }
  if (first.start.y !== second.start.y) return null
  const start = Math.max(Math.min(first.start.x, first.end.x), Math.min(second.start.x, second.end.x))
  const end = Math.min(Math.max(first.start.x, first.end.x), Math.max(second.start.x, second.end.x))
  return start <= end ? { x: start, y: first.start.y } : null
}

export function findUnapprovedRouteCrossings(routes: readonly (MapRoute | MapTransferRoute)[] = [...MAP_ROUTES, ...MAP_TRANSFER_ROUTES]): readonly RouteCrossing[] {
  const crossings: RouteCrossing[] = []
  routes.forEach((firstRoute, firstIndex) => {
    routes.slice(firstIndex + 1).forEach((secondRoute) => {
      routeSegments(firstRoute).forEach((firstSegment) => {
        routeSegments(secondRoute).forEach((secondSegment) => {
          const point = crossingPoint(firstSegment, secondSegment)
          if (point && !(isCorridorJunction(point) && isCorridorSegment(firstSegment) && isCorridorSegment(secondSegment))) {
            crossings.push({ firstRouteId: firstRoute.id, secondRouteId: secondRoute.id, point })
          }
          const overlap = collinearOverlapPoint(firstSegment, secondSegment)
          if (overlap && !(isCorridorSegment(firstSegment) && isCorridorSegment(secondSegment))) {
            crossings.push({ firstRouteId: firstRoute.id, secondRouteId: secondRoute.id, point: overlap })
          }
        })
      })
    })
  })
  return crossings
}
