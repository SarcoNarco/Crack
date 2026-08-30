import { describe, expect, it } from 'vitest'
import { isPresentationEvent } from './api'
import { previewEvents } from './fixtures'

describe('presentation event transport validation', () => {
  it('accepts a valid recorded fixture event', () => {
    expect(isPresentationEvent(previewEvents('success')[0])).toBe(true)
  })

  it.each([null, []])('rejects invalid metadata container %p', (metadata) => {
    const event = { ...previewEvents('success')[0], metadata }
    expect(isPresentationEvent(event)).toBe(false)
  })
})
