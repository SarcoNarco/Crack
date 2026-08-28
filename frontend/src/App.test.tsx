import { StrictMode } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import { previewEvents } from './fixtures'
import type { ConsoleTransport } from './api'
import type { PresentationEvent, RunStatus } from './types'

describe('live operations console', () => {
  it('shows the successful replay with the truthful Student A and Student B story', () => {
    render(<App preview="success" />)
    expect(screen.getByText('REPLAY / SYNTHETIC PREVIEW')).toBeInTheDocument()
    expect(screen.getByText('Student B lists their own submission')).toBeInTheDocument()
    expect(screen.getByText('Student A requests that submission detail')).toBeInTheDocument()
    expect(screen.getByText('Exact-submission match observed')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Cross-student detail read verified.' })).toBeInTheDocument()
  })

  it('switches presentation-only simple and technical modes', async () => {
    const user = userEvent.setup()
    render(<App preview="success" />)
    expect(screen.queryByText('reset:preview-a:state-sha256:school-preview-state')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Technical' }))
    expect(screen.getByText('reset:preview-a:state-sha256:school-preview-state')).toBeInTheDocument()
    expect(screen.getByText('reset:preview-b:state-sha256:school-preview-state')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Technical' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('presents the ordinary-code consensus truth table without model voting language', () => {
    render(<App preview="success" />)
    expect(screen.getByText('Exact-submission predicate')).toBeInTheDocument()
    expect(screen.getByText('Models plan. Code decides.')).toBeInTheDocument()
    expect(screen.getByText('Two passes → verified')).toBeInTheDocument()
    expect(screen.getByText('Incomplete provider or schema execution → no verdict')).toBeInTheDocument()
    expect(screen.queryByText(/models vote/i)).not.toBeInTheDocument()
  })

  it('shows a report affordance only after report generation', () => {
    const events = previewEvents('success')
    const reportIndex = events.findIndex((event) => event.type === 'report.generated')
    const first = render(<App preview={null} initialEvents={events.slice(0, reportIndex)} />)
    expect(screen.queryByText('Open exact Sprint 12 HTML report')).not.toBeInTheDocument()
    first.unmount()
    render(<App preview={null} initialEvents={events} />)
    expect(screen.getByRole('link', { name: 'Open exact Sprint 12 HTML report' })).toHaveAttribute(
      'href',
      `/api/demo-runs/${events[0].session_id}/report`,
    )
  })

  it('shows precise safe failure and no finding, verdict, or report', () => {
    render(<App preview="failure" />)
    expect(screen.getByRole('heading', { name: 'Run stopped safely.' })).toBeInTheDocument()
    expect(screen.getByText('No verdict')).toBeInTheDocument()
    expect(screen.queryByText(/Finding ID/)).not.toBeInTheDocument()
    expect(screen.queryByText(/HTML report/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Mapper: failed' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Authorization tester: blocked' })).toBeInTheDocument()
  })

  it.each(['unverified', 'inconclusive'])(
    'does not display a finding for a %s terminal verdict',
    (verdict) => {
      const base = previewEvents('success')
      const events = base
        .filter((event) => event.type !== 'finding.recorded')
        .map((event) => {
          if (event.type === 'consensus.completed' || event.type === 'session.completed') {
            return { ...event, metadata: { ...event.metadata, verdict, finding_id: null } }
          }
          return event
        }) as PresentationEvent[]
      render(<App preview={null} initialEvents={events} />)
      expect(screen.queryByText(/Finding ID/)).not.toBeInTheDocument()
      expect(screen.getAllByText(verdict, { exact: false }).length).toBeGreaterThan(0)
    },
  )

  it('disables the run button while a received session is active', () => {
    render(<App preview={null} initialEvents={previewEvents('success').slice(0, 1)} />)
    expect(screen.getByRole('button', { name: 'Contained run active' })).toBeDisabled()
  })

  it('has keyboard-operable labelled controls and a polite announcement', async () => {
    const user = userEvent.setup()
    render(<App preview="success" />)
    const modes = screen.getByRole('group', { name: 'Display mode' })
    expect(within(modes).getByRole('button', { name: 'Simple' })).toHaveAttribute('aria-pressed', 'true')
    await user.tab()
    expect(document.activeElement).toHaveAttribute('href', '#main-content')
    expect(document.querySelector('[aria-live="polite"]')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Inspect event 0/ })).toBeInTheDocument()
  })

  it('renders long identifiers in wrapping technical containers', async () => {
    const user = userEvent.setup()
    const events = previewEvents('success').map((event) =>
      event.type === 'session.completed'
        ? { ...event, metadata: { ...event.metadata, verifier_run_id: `verifier:${'long-id-'.repeat(24)}` } }
        : event,
    )
    render(<App preview={null} initialEvents={events} />)
    await user.click(screen.getByRole('button', { name: 'Technical' }))
    const runIds = screen.getAllByText(`verifier:${'long-id-'.repeat(24)}`)
    expect(runIds.length).toBeGreaterThan(0)
    expect(runIds.every((runId) => runId.classList.contains('wrap'))).toBe(true)
  })

  it('renders reconnect replay without duplicate feed entries', () => {
    const source = previewEvents('reconnect')
    render(<App preview="reconnect" />)
    const unique = new Set(source.map((event) => event.sequence))
    expect(screen.getAllByRole('button', { name: /^Inspect event/ })).toHaveLength(unique.size)
  })

  it('reopens a URL-bound session without starting another run', async () => {
    const events = previewEvents('reconnect')
    const status: RunStatus = {
      session_id: events[0].session_id,
      state: 'completed',
      stage: 'session',
      last_sequence: events.at(-1)!.sequence,
      terminal: true,
      events_url: `/api/demo-runs/${events[0].session_id}/events`,
    }
    const start = vi.fn<ConsoleTransport['start']>()
    const observe = vi.fn<ConsoleTransport['observe']>().mockResolvedValue(status)
    const subscribe = vi.fn<ConsoleTransport['subscribe']>((_status, onEvent) => {
      for (const event of events) onEvent(event)
      return () => undefined
    })
    window.history.replaceState({}, '', `?session=${events[0].session_id}`)
    render(<App preview={null} transport={{ start, observe, subscribe }} />)
    expect(await screen.findByRole('heading', { name: 'Cross-student detail read verified.' })).toBeInTheDocument()
    expect(observe).toHaveBeenCalledWith(events[0].session_id)
    expect(start).not.toHaveBeenCalled()
    expect(screen.getAllByRole('button', { name: /^Inspect event/ })).toHaveLength(
      new Set(events.map((event) => event.sequence)).size,
    )
    window.history.replaceState({}, '', '/')
  })

  it('restores one failed-session subscription across the Strict Mode remount', async () => {
    const events = previewEvents('failure').slice(0, 3).map((event, sequence) => ({
      ...event,
      sequence,
      session_id: 'demo:f8e7fdcf-28a0-4939-84a5-055fc5d1ca79',
      ...(sequence === 1 ? {
        type: 'preflight.started',
        stage: 'preflight' as const,
        state: 'active' as const,
        headline: 'Fixed preflight started',
      } : {}),
      ...(sequence === 2 ? {
        type: 'session.failed',
        stage: 'preflight' as const,
        state: 'failed' as const,
        headline: 'Contained run stopped safely',
        explanation: 'The current stage did not complete, so downstream stages were not activated and no result was invented.',
        metadata: { failed_stage: 'preflight', error_code: 'stage_execution_failed' },
      } : {}),
    }))
    const status: RunStatus = {
      session_id: events[0].session_id,
      state: 'failed',
      stage: 'preflight',
      last_sequence: 2,
      terminal: true,
      events_url: `/api/demo-runs/${events[0].session_id}/events`,
    }
    const start = vi.fn<ConsoleTransport['start']>()
    const observe = vi.fn<ConsoleTransport['observe']>().mockResolvedValue(status)
    const close = vi.fn()
    const subscribe = vi.fn<ConsoleTransport['subscribe']>((_status, onEvent) => {
      for (const event of events) onEvent(event)
      return close
    })
    window.history.replaceState({}, '', `?session=${events[0].session_id}`)
    const view = render(<StrictMode><App preview={null} transport={{ start, observe, subscribe }} /></StrictMode>)

    expect(await screen.findByRole('heading', { name: 'Run stopped safely.' })).toBeInTheDocument()
    expect(observe).toHaveBeenCalledTimes(2)
    expect(subscribe).toHaveBeenCalledTimes(1)
    expect(start).not.toHaveBeenCalled()
    expect(screen.getAllByRole('button', { name: /^Inspect event/ })).toHaveLength(3)
    expect(screen.getByText('No verdict')).toBeInTheDocument()

    view.unmount()
    expect(close).toHaveBeenCalledTimes(1)
    window.history.replaceState({}, '', '/')
  })

  it('closes a restored subscription before starting a new contained run', async () => {
    const events = previewEvents('failure')
    const restoredStatus: RunStatus = {
      session_id: events[0].session_id,
      state: 'failed',
      stage: 'mapper',
      last_sequence: events.at(-1)!.sequence,
      terminal: true,
      events_url: `/api/demo-runs/${events[0].session_id}/events`,
    }
    const nextStatus: RunStatus = {
      session_id: 'demo:00000000-0000-4000-8000-000000000099',
      state: 'active',
      stage: 'session',
      last_sequence: 0,
      terminal: false,
      events_url: '/api/demo-runs/demo:00000000-0000-4000-8000-000000000099/events',
    }
    const closeRestored = vi.fn()
    const closeNext = vi.fn()
    const start = vi.fn<ConsoleTransport['start']>().mockResolvedValue(nextStatus)
    const observe = vi.fn<ConsoleTransport['observe']>().mockResolvedValue(restoredStatus)
    const subscribe = vi.fn<ConsoleTransport['subscribe']>()
      .mockImplementationOnce((_status, onEvent) => {
        for (const event of events) onEvent(event)
        return closeRestored
      })
      .mockReturnValueOnce(closeNext)
    window.history.replaceState({}, '', `?session=${events[0].session_id}`)
    render(<App preview={null} transport={{ start, observe, subscribe }} />)
    await screen.findByRole('heading', { name: 'Run stopped safely.' })

    await userEvent.click(screen.getByRole('button', { name: 'Start contained verification run' }))

    expect(closeRestored).toHaveBeenCalledTimes(1)
    expect(start).toHaveBeenCalledTimes(1)
    expect(subscribe).toHaveBeenCalledTimes(2)
    window.history.replaceState({}, '', '/')
  })

  it('shows a malformed stored replay as a visible failure without starting', async () => {
    const start = vi.fn<ConsoleTransport['start']>()
    const observe = vi.fn<ConsoleTransport['observe']>()
      .mockRejectedValue(new Error('The recorded presentation failed validation.'))
    const subscribe = vi.fn<ConsoleTransport['subscribe']>()
    window.history.replaceState({}, '', '?session=demo:00000000-0000-4000-8000-000000000098')
    render(<App preview={null} transport={{ start, observe, subscribe }} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('failed validation')
    expect(start).not.toHaveBeenCalled()
    expect(subscribe).not.toHaveBeenCalled()
    window.history.replaceState({}, '', '/')
  })
})
