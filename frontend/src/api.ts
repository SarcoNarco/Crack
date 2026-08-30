import { isPresentationEventType, type PresentationEvent, type RunStatus } from './types'

export interface ConsoleTransport {
  start(): Promise<RunStatus>
  observe(sessionId: string): Promise<RunStatus>
  subscribe(
    status: RunStatus,
    onEvent: (event: PresentationEvent) => void,
    onError: (message: string) => void,
  ): () => void
}

export function isPresentationEvent(value: unknown): value is PresentationEvent {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.session_id === 'string' &&
    Number.isInteger(candidate.sequence) &&
    isPresentationEventType(candidate.type) &&
    typeof candidate.timestamp === 'string' &&
    typeof candidate.stage === 'string' &&
    typeof candidate.state === 'string' &&
    typeof candidate.headline === 'string' &&
    typeof candidate.explanation === 'string' &&
    typeof candidate.metadata === 'object' && candidate.metadata !== null && !Array.isArray(candidate.metadata)
  )
}

export const liveTransport: ConsoleTransport = {
  async start() {
    const response = await fetch('/api/demo-runs', { method: 'POST' })
    if (!response.ok) {
      const fallback = response.status === 409
        ? 'Another contained run is already active.'
        : 'The contained run could not be accepted.'
      throw new Error(fallback)
    }
    return response.json() as Promise<RunStatus>
  },

  async observe(sessionId) {
    const response = await fetch(`/api/demo-runs/${encodeURIComponent(sessionId)}`)
    if (!response.ok) throw new Error('The recorded contained session could not be reopened.')
    return response.json() as Promise<RunStatus>
  },

  subscribe(status, onEvent, onError) {
    const source = new EventSource(status.events_url)
    source.onmessage = (message) => {
      try {
        const event: unknown = JSON.parse(message.data)
        if (!isPresentationEvent(event)) throw new Error('invalid event schema')
        onEvent(event)
        if (event.type === 'session.completed' || event.type === 'session.failed') source.close()
      } catch {
        source.close()
        onError('The presentation stream failed schema validation.')
      }
    }
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) {
        onError('The presentation stream disconnected before a terminal event.')
      }
    }
    return () => source.close()
  },
}
