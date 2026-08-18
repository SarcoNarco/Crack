import { consoleReducer, deriveConsole, initialConsoleState } from './reducer'
import { previewEvents } from './fixtures'
import type { PresentationEvent } from './types'

function reduce(events: PresentationEvent[]) {
  return events.reduce(
    (state, event) => consoleReducer(state, { type: 'event', event }),
    initialConsoleState,
  )
}

describe('console event reducer', () => {
  it('derives pending, active, completed, failed, and blocked stage states', () => {
    expect(deriveConsole(initialConsoleState).stages.preflight).toBe('pending')
    const active = deriveConsole(reduce(previewEvents('success').slice(0, 2)))
    expect(active.stages.preflight).toBe('active')
    const completed = deriveConsole(reduce(previewEvents('success')))
    expect(completed.stages.report).toBe('completed')
    const failed = deriveConsole(reduce(previewEvents('failure')))
    expect(failed.stages.mapper).toBe('failed')
    expect(failed.stages.authorization).toBe('blocked')
    expect(failed.stages.report).toBe('blocked')
  })

  it('keeps received events ordered and ignores duplicate replay IDs', () => {
    const state = reduce(previewEvents('reconnect'))
    const sequences = state.events.map((event) => event.sequence)
    expect(sequences).toEqual([...sequences].sort((a, b) => a - b))
    expect(sequences).toHaveLength(new Set(sequences).size)
    expect(deriveConsole(state).sequenceGap).toBe(false)
  })

  it('never has both sequential verifier lanes active in the recorded fixture', () => {
    let state = initialConsoleState
    for (const event of previewEvents('success')) {
      state = consoleReducer(state, { type: 'event', event })
      const stages = deriveConsole(state).stages
      expect(stages.verifier_a === 'active' && stages.verifier_b === 'active').toBe(false)
    }
  })

  it('exposes a report only after report.generated and a finding only after finding.recorded', () => {
    const fixture = previewEvents('success')
    const reportIndex = fixture.findIndex((event) => event.type === 'report.generated')
    const findingIndex = fixture.findIndex((event) => event.type === 'finding.recorded')
    expect(deriveConsole(reduce(fixture.slice(0, reportIndex))).report).toBeNull()
    expect(deriveConsole(reduce(fixture.slice(0, reportIndex + 1))).report?.type).toBe('report.generated')
    expect(deriveConsole(reduce(fixture.slice(0, findingIndex))).finding).toBeNull()
    expect(deriveConsole(reduce(previewEvents('failure'))).finding).toBeNull()
  })
})
