import { isMapAudioCueId, mapAudioCue, type MapAudioCueId } from './audio-manifest'

export interface ReplayAudioElement {
  src: string
  volume: number
  currentTime: number
  preload?: string
  play(): Promise<void> | void
  pause(): void
}

export type ReplayAudioFactory = (src: string) => ReplayAudioElement

export interface ReplayAudioControllerOptions {
  readonly audioFactory?: ReplayAudioFactory
  readonly enabled?: boolean
}

function browserAudioFactory(src: string): ReplayAudioElement {
  return new globalThis.Audio(src)
}

/**
 * User-armed, single-channel playback for fixed replay cues. This controller
 * accepts cue IDs only; event metadata and event-provided URLs never enter it.
 */
export class ReplayAudioController {
  private readonly audioFactory: ReplayAudioFactory
  private activeAudio: ReplayAudioElement | null = null
  private activeGeneration = 0
  private armed = false
  private enabled: boolean
  private disposed = false

  constructor(options: ReplayAudioControllerOptions = {}) {
    this.audioFactory = options.audioFactory ?? browserAudioFactory
    this.enabled = options.enabled ?? true
  }

  isArmed(): boolean {
    return this.armed && !this.disposed
  }

  isEnabled(): boolean {
    return this.enabled && !this.disposed
  }

  /** Call only from the user-initiated replay action. */
  armReplay(): void {
    if (this.disposed) return
    this.stopActive()
    this.armed = true
  }

  arm(): void {
    this.armReplay()
  }

  setEnabled(enabled: boolean): void {
    if (this.disposed || this.enabled === enabled) return
    this.enabled = enabled
    if (!enabled) this.stopActive()
  }

  toggleEnabled(): boolean {
    this.setEnabled(!this.enabled)
    return this.enabled
  }

  /** Plays one fixed cue, stopping any prior cue first. */
  playCue(cueId: MapAudioCueId): boolean {
    if (this.disposed || !this.armed || !this.enabled || !isMapAudioCueId(cueId)) return false

    this.stopActive()
    const cue = mapAudioCue(cueId)
    let audio: ReplayAudioElement
    try {
      audio = this.audioFactory(cue.src)
      audio.preload = 'auto'
      audio.volume = Math.min(0.12, Math.max(0, cue.volume))
      audio.currentTime = 0
    } catch {
      return false
    }

    const generation = this.activeGeneration
    this.activeAudio = audio
    try {
      const result = audio.play()
      if (result && typeof result.then === 'function') {
        void result.catch(() => {
          if (this.activeGeneration === generation && this.activeAudio === audio) this.activeAudio = null
        })
      }
    } catch {
      if (this.activeGeneration === generation && this.activeAudio === audio) this.activeAudio = null
      return false
    }
    return true
  }

  play(cueId: MapAudioCueId): boolean {
    return this.playCue(cueId)
  }

  stop(): void {
    this.stopActive()
    this.armed = false
  }

  reset(): void {
    if (this.disposed) return
    this.stopActive()
    this.armed = false
  }

  destroy(): void {
    if (this.disposed) return
    this.reset()
    this.disposed = true
  }

  private stopActive(): void {
    this.activeGeneration += 1
    const audio = this.activeAudio
    this.activeAudio = null
    if (!audio) return
    try {
      audio.pause()
      audio.currentTime = 0
    } catch {
      // Browser media can throw while a source is unloading; state is cleared.
    }
  }
}
