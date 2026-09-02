export const MAP_AUDIO_CUE_IDS = [
  'footsteps',
  'scan',
  'probe',
  'pickaxe',
  'beam',
  'consensus',
  'failure',
] as const

export type MapAudioCueId = typeof MAP_AUDIO_CUE_IDS[number]

export interface MapAudioCue {
  readonly id: MapAudioCueId
  readonly src: string
  readonly volume: number
  readonly durationMs: number
}

/** Fixed local-only WAV cues. Event data cannot select an asset or URL. */
export const MAP_AUDIO_MANIFEST: Readonly<Record<MapAudioCueId, MapAudioCue>> = {
  footsteps: { id: 'footsteps', src: '/map/audio/footsteps.wav', volume: 0.035, durationMs: 280 },
  scan: { id: 'scan', src: '/map/audio/scan.wav', volume: 0.06, durationMs: 400 },
  probe: { id: 'probe', src: '/map/audio/probe.wav', volume: 0.05, durationMs: 210 },
  pickaxe: { id: 'pickaxe', src: '/map/audio/pickaxe.wav', volume: 0.07, durationMs: 220 },
  beam: { id: 'beam', src: '/map/audio/beam.wav', volume: 0.055, durationMs: 320 },
  consensus: { id: 'consensus', src: '/map/audio/consensus.wav', volume: 0.08, durationMs: 340 },
  failure: { id: 'failure', src: '/map/audio/failure.wav', volume: 0.07, durationMs: 380 },
}

export function isMapAudioCueId(value: unknown): value is MapAudioCueId {
  return typeof value === 'string' && (MAP_AUDIO_CUE_IDS as readonly string[]).includes(value)
}

export function mapAudioCue(id: MapAudioCueId): MapAudioCue {
  return MAP_AUDIO_MANIFEST[id]
}
