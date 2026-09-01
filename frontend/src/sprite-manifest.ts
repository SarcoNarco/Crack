import type { MapAgentId } from './map-layout'

export const SPRITE_FRAME_SIZE = 32
export const SPRITE_SHEET_WIDTH = 256
export const SPRITE_SHEET_HEIGHT = 32

export const SPRITE_FRAME_NAMES = [
  'down0', 'down1', 'right0', 'right1', 'up0', 'up1', 'left0', 'left1',
] as const

export type SpriteFrameName = typeof SPRITE_FRAME_NAMES[number]

export interface SpriteFrame {
  readonly name: SpriteFrameName
  readonly index: number
  readonly x: number
  readonly y: 0
  readonly width: typeof SPRITE_FRAME_SIZE
  readonly height: typeof SPRITE_FRAME_SIZE
}

/** Fixed local-only sprite sheets. Event data cannot select an asset or frame. */
export const AGENT_SPRITE_MANIFEST: Readonly<Record<MapAgentId, {
  readonly label: string
  readonly sheet: string
  readonly frames: readonly SpriteFrame[]
}>> = {
  mapper: { label: 'MAPPER', sheet: '/map/agents/mapper-walk.png', frames: frames() },
  'authorization-tester': { label: 'AUTH TESTER', sheet: '/map/agents/authorization-tester-walk.png', frames: frames() },
  'verifier-a': { label: 'VERIFIER A', sheet: '/map/agents/verifier-a-walk.png', frames: frames() },
  'verifier-b': { label: 'VERIFIER B', sheet: '/map/agents/verifier-b-walk.png', frames: frames() },
}

function frames(): readonly SpriteFrame[] {
  return SPRITE_FRAME_NAMES.map((name, index) => ({
    name,
    index,
    x: index * SPRITE_FRAME_SIZE,
    y: 0,
    width: SPRITE_FRAME_SIZE,
    height: SPRITE_FRAME_SIZE,
  }))
}

export function spriteFrame(agentId: MapAgentId, name: SpriteFrameName): SpriteFrame {
  return AGENT_SPRITE_MANIFEST[agentId].frames.find((frame) => frame.name === name)!
}
