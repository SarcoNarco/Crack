import type { PresentationEvent } from './types'

export interface ScheduledReplayEvent {
  event: PresentationEvent
  dueMs: number
}

export const SUCCESS_REPLAY_DUE_MS = [
  0, 1_000, 2_000, 3_000, 6_500, 7_000, 7_600, 8_200,
  9_000, 9_050, 15_000, 19_750, 19_800, 19_850, 19_900, 20_000,
  20_050, 25_000, 30_950, 31_000, 31_050, 31_100, 31_200, 31_250,
  36_000, 40_400, 40_500, 42_000, 43_500, 45_000, 47_000, 48_000,
] as const

// The committed failure fixture has five accepted events. It stops after the
// mapper activation and reaches its safe terminal state at 4.8 seconds.
const FAILURE_REPLAY_DUE_MS = [0, 1_000, 2_000, 3_000, 4_800] as const

type ScheduledPreviewKind = 'success' | 'failure'

function assertFixtureOrder(events: readonly PresentationEvent[], dueTimes: readonly number[]): void {
  if (events.length !== dueTimes.length) {
    throw new Error('The committed replay fixture no longer matches its fixed schedule.')
  }
  for (let index = 0; index < events.length; index += 1) {
    if (events[index].sequence !== index || (index > 0 && events[index - 1].sequence >= events[index].sequence)) {
      throw new Error('The committed replay fixture must retain its original unique sequence order.')
    }
  }
}

export function schedulePreviewReplay(
  kind: ScheduledPreviewKind,
  events: readonly PresentationEvent[],
): readonly ScheduledReplayEvent[] {
  const dueTimes = kind === 'success' ? SUCCESS_REPLAY_DUE_MS : FAILURE_REPLAY_DUE_MS
  assertFixtureOrder(events, dueTimes)
  return events.map((event, index) => ({ event, dueMs: dueTimes[index] }))
}
