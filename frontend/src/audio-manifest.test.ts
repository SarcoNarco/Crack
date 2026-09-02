import { describe, expect, it } from 'vitest'
import { MAP_AUDIO_CUE_IDS, MAP_AUDIO_MANIFEST, isMapAudioCueId } from './audio-manifest'

describe('Sprint 25 fixed audio manifest', () => {
  it('contains exactly seven short local mono cue paths with safe low volume', () => {
    expect(MAP_AUDIO_CUE_IDS).toEqual(['footsteps', 'scan', 'probe', 'pickaxe', 'beam', 'consensus', 'failure'])
    for (const id of MAP_AUDIO_CUE_IDS) {
      const cue = MAP_AUDIO_MANIFEST[id]
      expect(cue.src).toBe(`/map/audio/${id}.wav`)
      expect(cue.src).not.toMatch(/^https?:/)
      expect(cue.volume).toBeGreaterThanOrEqual(0)
      expect(cue.volume).toBeLessThanOrEqual(0.12)
      expect(cue.durationMs).toBeGreaterThan(0)
      expect(cue.durationMs).toBeLessThanOrEqual(500)
    }
  })

  it('rejects event-controlled cue values', () => {
    expect(isMapAudioCueId('scan')).toBe(true)
    expect(isMapAudioCueId('/evil.wav')).toBe(false)
    expect(isMapAudioCueId({ id: 'scan' })).toBe(false)
  })
})
