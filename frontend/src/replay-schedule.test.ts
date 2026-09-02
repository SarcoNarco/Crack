import { previewEvents } from './fixtures'
import { SUCCESS_REPLAY_DUE_MS, schedulePreviewReplay } from './replay-schedule'

describe('recorded preview replay schedule', () => {
  it('keeps every successful fixture event in its original unique order for exactly 48 seconds', () => {
    const events = previewEvents('success')
    const scheduled = schedulePreviewReplay('success', events)

    expect(scheduled).toHaveLength(32)
    expect(scheduled.map(({ dueMs }) => dueMs)).toEqual(SUCCESS_REPLAY_DUE_MS)
    expect(scheduled.map(({ event }) => event.sequence)).toEqual([...Array(32).keys()])
    expect(scheduled.map(({ event }) => event.type)).toEqual(events.map((event) => event.type))
    expect(scheduled[0].dueMs).toBe(0)
    expect(scheduled.at(-1)?.dueMs).toBe(48_000)
    expect(scheduled.every(({ dueMs }, index) => index === 0 || dueMs > scheduled[index - 1].dueMs)).toBe(true)
  })

  it('keeps the complete failure fixture ordered and bounded', () => {
    const events = previewEvents('failure')
    const scheduled = schedulePreviewReplay('failure', events)

    expect(scheduled.map(({ event }) => event.sequence)).toEqual(events.map((event) => event.sequence))
    expect(scheduled.map(({ event }) => event.type)).toEqual(events.map((event) => event.type))
    expect(scheduled.at(-1)?.dueMs).toBeLessThanOrEqual(48_000)
  })

  it('fails closed when a fixed fixture loses its original unique order', () => {
    const events = previewEvents('success')
    expect(() => schedulePreviewReplay('success', [...events.slice(0, 1), events[0], ...events.slice(2)])).toThrow(
      'original unique sequence order',
    )
  })
})
