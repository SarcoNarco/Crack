import { describe, expect, it } from 'vitest'
// Vitest executes this asset contract in Node; browser tsconfig omits Node globals.
// @ts-expect-error node:fs is available to Vitest.
import { readFileSync } from 'node:fs'
import { MAP_AGENT_IDS } from './map-layout'
import {
  AGENT_SPRITE_MANIFEST,
  SPRITE_FRAME_NAMES,
  SPRITE_FRAME_SIZE,
  SPRITE_SHEET_HEIGHT,
  SPRITE_SHEET_WIDTH,
} from './sprite-manifest'

declare const process: { cwd(): string }

describe('Sprint 24 agent sprite manifest', () => {
  it('pins four local 256 by 32 sheets and the shared cardinal frame order', () => {
    expect(SPRITE_FRAME_NAMES).toEqual(['down0', 'down1', 'right0', 'right1', 'up0', 'up1', 'left0', 'left1'])
    expect(Object.keys(AGENT_SPRITE_MANIFEST)).toEqual(MAP_AGENT_IDS)
    for (const agentId of MAP_AGENT_IDS) {
      const manifest = AGENT_SPRITE_MANIFEST[agentId]
      expect(manifest.sheet).toBe(`/map/agents/${agentId}-walk.png`)
      expect(manifest.frames.map((frame) => frame.name)).toEqual(SPRITE_FRAME_NAMES)
      expect(manifest.frames.map((frame) => frame.x)).toEqual([0, 32, 64, 96, 128, 160, 192, 224])
      expect(manifest.frames.every((frame) => frame.width === SPRITE_FRAME_SIZE && frame.height === SPRITE_FRAME_SIZE && frame.y === 0)).toBe(true)
      const png = readFileSync(`${process.cwd()}/public${manifest.sheet}`)
      expect(png.subarray(1, 4).toString('ascii')).toBe('PNG')
      expect(png.readUInt32BE(16)).toBe(SPRITE_SHEET_WIDTH)
      expect(png.readUInt32BE(20)).toBe(SPRITE_SHEET_HEIGHT)
    }
  })
})
