import { STAGES, type EventState, type PresentationEvent, type StageKey } from './types'

export interface ConsoleState {
  events: PresentationEvent[]
  streamError: string | null
}

export interface DerivedConsole {
  stages: Record<StageKey, EventState>
  terminal: PresentationEvent | null
  active: boolean
  finding: PresentationEvent | null
  report: PresentationEvent | null
  consensus: PresentationEvent | null
  sequenceGap: boolean
}

export const initialConsoleState: ConsoleState = { events: [], streamError: null }

export type ConsoleAction =
  | { type: 'reset' }
  | { type: 'event'; event: PresentationEvent }
  | { type: 'error'; message: string }

export function consoleReducer(state: ConsoleState, action: ConsoleAction): ConsoleState {
  if (action.type === 'reset') return initialConsoleState
  if (action.type === 'error') return { ...state, streamError: action.message }
  if (state.events.some((event) => event.sequence === action.event.sequence)) return state
  const events = [...state.events, action.event].sort((a, b) => a.sequence - b.sequence)
  return { ...state, events }
}

export function deriveConsole(state: ConsoleState): DerivedConsole {
  const stages = Object.fromEntries(
    STAGES.map(({ key }) => [key, 'pending']),
  ) as Record<StageKey, EventState>
  let terminal: PresentationEvent | null = null
  let finding: PresentationEvent | null = null
  let report: PresentationEvent | null = null
  let consensus: PresentationEvent | null = null

  for (const event of state.events) {
    if (event.stage !== 'session') stages[event.stage] = event.state
    if (event.type === 'finding.recorded') finding = event
    if (event.type === 'report.generated') report = event
    if (event.type === 'consensus.completed') consensus = event
    if (event.type === 'session.completed' || event.type === 'session.failed') terminal = event
  }

  if (terminal?.type === 'session.failed') {
    const failedIndex = STAGES.findIndex(({ key }) => key === terminal?.stage)
    if (failedIndex >= 0) {
      stages[STAGES[failedIndex].key] = 'failed'
      for (const stage of STAGES.slice(failedIndex + 1)) {
        if (stages[stage.key] === 'pending') stages[stage.key] = 'blocked'
      }
    }
  }

  const sequenceGap = state.events.some((event, index) => event.sequence !== index)
  return {
    stages,
    terminal,
    active: state.events.length > 0 && terminal === null,
    finding,
    report,
    consensus,
    sequenceGap,
  }
}

export function eventsForStage(events: PresentationEvent[], stage: StageKey): PresentationEvent[] {
  return events.filter((event) => event.stage === stage)
}
