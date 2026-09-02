import { describe, expect, it, vi } from 'vitest'
import { ReplayAudioController, type ReplayAudioElement } from './replay-audio'

function fakeAudio(src: string): ReplayAudioElement & { playCount: number; pauseCount: number } {
  return {
    src,
    volume: 1,
    currentTime: 0,
    playCount: 0,
    pauseCount: 0,
    play() { this.playCount += 1 },
    pause() { this.pauseCount += 1 },
  }
}

describe('Sprint 25 replay audio controller', () => {
  it('does not play before explicit replay arm and uses fixed cue path after arm', () => {
    const created: Array<ReplayAudioElement & { playCount: number; pauseCount: number }> = []
    const controller = new ReplayAudioController({ audioFactory: (src) => {
      const audio = fakeAudio(src)
      created.push(audio)
      return audio
    } })
    expect(controller.playCue('scan')).toBe(false)
    expect(created).toHaveLength(0)
    controller.armReplay()
    expect(controller.playCue('scan')).toBe(true)
    expect(created[0].src).toBe('/map/audio/scan.wav')
    expect(created[0].playCount).toBe(1)
  })

  it('muted mode stops current playback and blocks later cues', () => {
    const audio = fakeAudio('/map/audio/scan.wav')
    const controller = new ReplayAudioController({ audioFactory: () => audio })
    controller.arm()
    expect(controller.play('scan')).toBe(true)
    controller.setEnabled(false)
    expect(audio.pauseCount).toBe(1)
    expect(controller.play('probe')).toBe(false)
  })

  it('stops prior family before starting exactly one new cue at a safe volume', () => {
    const created: Array<ReplayAudioElement & { playCount: number; pauseCount: number }> = []
    const controller = new ReplayAudioController({ audioFactory: (src) => {
      const audio = fakeAudio(src)
      created.push(audio)
      return audio
    } })
    controller.arm()
    expect(controller.play('pickaxe')).toBe(true)
    expect(controller.play('beam')).toBe(true)
    expect(created[0].pauseCount).toBe(1)
    expect(created).toHaveLength(2)
    expect(created[1].volume).toBeLessThanOrEqual(0.12)
    expect(created[1].src).toBe('/map/audio/beam.wav')
  })

  it('stop, reset, and destroy cancel playback and prevent stale revival', () => {
    vi.useFakeTimers()
    try {
      const audio = fakeAudio('/map/audio/scan.wav')
      const controller = new ReplayAudioController({ audioFactory: () => audio })
      controller.arm()
      controller.play('scan')
      controller.stop()
      expect(audio.pauseCount).toBe(1)
      expect(controller.play('scan')).toBe(false)
      controller.reset()
      expect(controller.isArmed()).toBe(false)
      expect(controller.play('scan')).toBe(false)
      controller.arm()
      controller.play('scan')
      controller.destroy()
      expect(audio.pauseCount).toBe(2)
      expect(controller.play('scan')).toBe(false)
      vi.runAllTimers()
    } finally {
      vi.useRealTimers()
    }
  })

  it('does not leak rejected browser play promises', async () => {
    const audio = fakeAudio('/map/audio/scan.wav')
    audio.play = vi.fn(() => Promise.reject(new Error('gesture required')))
    const controller = new ReplayAudioController({ audioFactory: () => audio })
    controller.arm()
    expect(controller.play('scan')).toBe(true)
    await Promise.resolve()
    expect(() => controller.stop()).not.toThrow()
  })
})
