import { describe, expect, it } from 'vitest'
// Vitest executes this asset contract in Node; the browser app tsconfig intentionally omits Node globals.
// @ts-expect-error node:fs is available to the Vitest runtime.
import { readFileSync } from 'node:fs'
import { ARCHITECTURE_NODE_IDS } from './architecture'
import {
  findUnapprovedRouteCrossings,
  isBoundsInsideMap,
  isCardinalRoute,
  isPointInsideBounds,
  isPointInsideMap,
  MAP_AGENT_IDS,
  MAP_HEIGHT,
  MAP_ROOM_IDS,
  MAP_ROOMS,
  MAP_ROUTES,
  MAP_TRANSFER_ROUTES,
  MAP_WIDTH,
  STAGING_DOCK,
  STAGING_SLOTS,
} from './map-layout'

declare const process: { cwd(): string }

describe('Sprint 23 static floor geometry', () => {
  const assetRoot = `${process.cwd()}/public/map/`

  it('uses the fixed 960 by 540 canvas and canonical room order', () => {
    expect([MAP_WIDTH, MAP_HEIGHT]).toEqual([960, 540])
    expect(MAP_ROOM_IDS).toBe(ARCHITECTURE_NODE_IDS)
    expect(MAP_ROOMS.map((room) => room.id)).toEqual(ARCHITECTURE_NODE_IDS)
    expect(MAP_ROOMS.map((room) => room.label)).toEqual([
      'Browser portal',
      'FastAPI API',
      'Grade lifecycle',
      'Role and authentication',
      'SQLite persistence',
      'Submissions',
    ])
  })

  it('keeps room art and interaction points inside the fixed map without overlap', () => {
    for (const room of MAP_ROOMS) {
      expect(isBoundsInsideMap(room.bounds), room.id).toBe(true)
      expect(isPointInsideMap(room.interactionPoint), room.id).toBe(true)
      expect(isPointInsideBounds(room.interactionPoint, room.bounds), room.id).toBe(false)
    }
    for (const [index, room] of MAP_ROOMS.entries()) {
      for (const other of MAP_ROOMS.slice(index + 1)) {
        const overlaps = room.bounds.x < other.bounds.x + other.bounds.width
          && room.bounds.x + room.bounds.width > other.bounds.x
          && room.bounds.y < other.bounds.y + other.bounds.height
          && room.bounds.y + room.bounds.height > other.bounds.y
        expect(overlaps, `${room.id} overlaps ${other.id}`).toBe(false)
      }
    }
  })

  it('pins four ordered staging slots and dock points inside the staging dock', () => {
    expect(STAGING_SLOTS.map((slot) => slot.agentId)).toEqual(MAP_AGENT_IDS)
    expect(STAGING_SLOTS).toHaveLength(4)
    for (const slot of STAGING_SLOTS) {
      expect(isPointInsideBounds(slot.dockPoint, slot.bounds), slot.agentId).toBe(true)
      expect(isPointInsideBounds({ x: slot.bounds.x, y: slot.bounds.y }, STAGING_DOCK), slot.agentId).toBe(true)
      expect(isPointInsideBounds({ x: slot.bounds.x + slot.bounds.width, y: slot.bounds.y + slot.bounds.height }, STAGING_DOCK), slot.agentId).toBe(true)
    }
  })

  it('uses fixed cardinal routes with dock starts and room interaction ends', () => {
    expect(MAP_ROUTES.map((route) => route.id)).toEqual([
      'mapper-to-browser-portal',
      'mapper-to-fastapi-api',
      'authorization-tester-to-role-authentication',
      'authorization-tester-to-submissions',
      'authorization-tester-to-grade-lifecycle',
      'verifier-a-to-submissions',
      'verifier-a-to-grade-lifecycle',
      'verifier-b-to-submissions',
      'verifier-b-to-grade-lifecycle',
    ])
    for (const route of MAP_ROUTES) {
      const slot = STAGING_SLOTS.find((item) => item.agentId === route.agentId)!
      const room = MAP_ROOMS.find((item) => item.id === route.roomId)!
      expect(route.waypoints.length, route.id).toBeGreaterThanOrEqual(3)
      expect(route.waypoints[0], route.id).toEqual(slot.dockPoint)
      expect(route.waypoints.at(-1), route.id).toEqual(room.interactionPoint)
      expect(isCardinalRoute(route), route.id).toBe(true)
      expect(route.waypoints.every(isPointInsideMap), route.id).toBe(true)
    }
  })

  it('has no unrelated route crossings; shared geometry stays on authored corridors', () => {
    expect(findUnapprovedRouteCrossings()).toEqual([])
  })

  it('pins bounded cardinal submissions and grade-lifecycle transfer routes', () => {
    expect(MAP_TRANSFER_ROUTES.map((route) => route.id)).toEqual([
      'submissions-to-grade-lifecycle',
      'grade-lifecycle-to-submissions',
    ])
    for (const route of MAP_TRANSFER_ROUTES) {
      const from = MAP_ROOMS.find((room) => room.id === route.fromRoomId)!
      const to = MAP_ROOMS.find((room) => room.id === route.toRoomId)!
      expect(route.waypoints[0]).toEqual(from.interactionPoint)
      expect(route.waypoints.at(-1)).toEqual(to.interactionPoint)
      expect(isCardinalRoute(route), route.id).toBe(true)
      expect(route.waypoints.every(isPointInsideMap), route.id).toBe(true)
    }
  })

  it('rejects an injected perpendicular crossing outside an authored junction', () => {
    const crossingRoute = {
      id: 'injected-crossing',
      agentId: 'mapper' as const,
      roomId: 'browser-portal' as const,
      waypoints: [{ x: 500, y: 180 }, { x: 500, y: 300 }],
    }
    expect(findUnapprovedRouteCrossings([...MAP_ROUTES, crossingRoute])).toContainEqual(expect.objectContaining({
      secondRouteId: 'injected-crossing',
      point: { x: 500, y: 244 },
    }))
  })

  it('pins local raster dimensions and explicit asset provenance', () => {
    const dimensions = (relativePath: string) => {
      const png = readFileSync(`${assetRoot}${relativePath}`)
      expect(png.subarray(1, 4).toString('ascii')).toBe('PNG')
      return { width: png.readUInt32BE(16), height: png.readUInt32BE(20) }
    }
    expect(dimensions('crack-operations-floor.png')).toEqual({ width: 1664, height: 936 })
    for (const agentId of MAP_AGENT_IDS) {
      expect(dimensions(`agents/${agentId}.png`), agentId).toEqual({ width: 32, height: 32 })
    }
    const provenance = readFileSync(`${assetRoot}ASSET_PROVENANCE.md`, 'utf8')
    expect(provenance).toMatch(/license|rights/i)
    expect(provenance).toMatch(/OpenAI built-in ImageGen/)
    expect(provenance).toMatch(/no commercial-game assets/i)
  })
})
