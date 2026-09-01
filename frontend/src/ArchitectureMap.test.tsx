import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ArchitectureMap } from './ArchitectureMap'
import { previewEvents } from './fixtures'

const mapperEvent = () => previewEvents('success').find((event) => event.type === 'mapper.activated')!

afterEach(() => vi.useRealTimers())

describe('Sprint 24 architecture floor renderer', () => {
  it('renders six labelled rooms, nine fixed corridors, and four clipped local agents', () => {
    const { container } = render(<ArchitectureMap events={[]} />)
    expect(screen.getByRole('img', { name: /School portal operations floor/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'No presentation event received' })).toBeInTheDocument()
    expect(container.querySelector('.architecture-map')).toHaveAttribute('viewBox', '0 0 960 540')
    expect(screen.getByRole('region', { name: 'Scrollable operations floor' })).toHaveAttribute('tabindex', '0')
    expect(container.querySelectorAll('[data-room-id]')).toHaveLength(6)
    expect(container.querySelectorAll('[data-corridor-id]')).toHaveLength(9)
    const agents = container.querySelectorAll('[data-agent-id]')
    expect(agents).toHaveLength(4)
    expect([...agents].map((agent) => agent.getAttribute('data-agent-state'))).toEqual(['docked', 'docked', 'docked', 'docked'])
    for (const viewport of container.querySelectorAll('.architecture-agent-viewport')) {
      expect(viewport).toHaveAttribute('x', '-16')
      expect(viewport).toHaveAttribute('y', '-16')
      expect(viewport).toHaveAttribute('width', '32')
      expect(viewport).toHaveAttribute('height', '32')
      expect(viewport).toHaveAttribute('viewBox', '0 0 32 32')
      expect(viewport).toHaveAttribute('overflow', 'hidden')
    }
    expect(screen.getByText('STAGING DOCK')).toBeInTheDocument()
    expect(screen.getByText('MAPPER')).toBeInTheDocument()
    expect(screen.getByText('AUTH TESTER')).toBeInTheDocument()
    expect(screen.getByText('VERIFIER A')).toBeInTheDocument()
    expect(screen.getByText('VERIFIER B')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(container.querySelectorAll('.architecture-section [aria-live="polite"]')).toHaveLength(1)
  })

  it('keeps an initial completed preview docked, then queues later unique accepted events after empty replay state', () => {
    vi.useFakeTimers()
    const completed = previewEvents('success')
    const { container, rerender } = render(<ArchitectureMap events={completed} />)
    expect(container.querySelector('[data-agent-id="mapper"]')).toHaveAttribute('data-agent-state', 'docked')
    expect(container.querySelector('animateTransform')).not.toBeInTheDocument()

    rerender(<ArchitectureMap events={[]} generation={1} />)
    rerender(<ArchitectureMap events={[mapperEvent()]} generation={1} />)
    const mapper = container.querySelector('[data-agent-id="mapper"]')!
    expect(mapper).toHaveAttribute('data-agent-state', 'walk')
    expect(mapper).toHaveAttribute('data-agent-direction', 'right')
    expect(mapper).toHaveAttribute('data-agent-frame', 'right0')
    expect(mapper.querySelector('.architecture-agent-sprite')).toHaveAttribute('href', '/map/agents/mapper-walk.png')
    expect(mapper.querySelector('.architecture-agent-sprite')).toHaveAttribute('x', '-64')
    expect(mapper.querySelector('animateTransform')).toHaveAttribute('to', '49 0')
    expect(mapper.querySelector('animateTransform')).toHaveAttribute('additive', 'sum')
    expect(mapper.querySelector('animate[attributeName="x"]')).toHaveAttribute('values', '-64;-96;-64')
    expect(mapper.querySelector('animate[attributeName="x"]')).toHaveAttribute('repeatDur', '980ms')
  })

  it('arms a batched replay when a completed event list rewinds directly to its first event', () => {
    vi.useFakeTimers()
    const completed = previewEvents('success')
    const mapperIndex = completed.findIndex((event) => event.type === 'mapper.activated')
    const { container, rerender } = render(<ArchitectureMap events={completed} />)
    rerender(<ArchitectureMap events={completed.slice(0, 1)} />)
    expect(container.querySelectorAll('[data-agent-state="docked"]')).toHaveLength(4)
    rerender(<ArchitectureMap events={completed.slice(0, mapperIndex + 1)} />)
    expect(container.querySelector('[data-agent-id="mapper"]')).toHaveAttribute('data-agent-state', 'walk')
    expect(container.querySelector('[data-agent-id="mapper"] animateTransform')).toBeInTheDocument()
  })

  it('resets safely for a changed session and cancels queued work when unmounted', async () => {
    vi.useFakeTimers()
    const first = mapperEvent()
    const nextSession = { ...first, session_id: 'new-safe-session', sequence: 0, type: 'session.started' as const }
    const { container, rerender, unmount } = render(<ArchitectureMap events={[]} />)
    rerender(<ArchitectureMap events={[first]} generation={1} />)
    expect(container.querySelector('[data-agent-id="mapper"]')).toHaveAttribute('data-agent-state', 'walk')
    rerender(<ArchitectureMap events={[nextSession]} />)
    expect(container.querySelectorAll('[data-agent-state="docked"]')).toHaveLength(4)
    unmount()
    await act(async () => { await Promise.resolve() })
    act(() => vi.runOnlyPendingTimers())
    expect(vi.getTimerCount()).toBe(0)
  })

  it('preserves fixed status and labels in reduced-motion mode without a walking transform', () => {
    vi.useFakeTimers()
    const original = window.matchMedia
    window.matchMedia = vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })
    try {
      const { container, rerender } = render(<ArchitectureMap events={[]} />)
      rerender(<ArchitectureMap events={[mapperEvent()]} generation={1} />)
      expect(container.querySelector('[data-agent-id="mapper"]')).toHaveAttribute('data-agent-state', 'acknowledge')
      expect(container.querySelector('animateTransform')).not.toBeInTheDocument()
      expect(screen.getByText('MAPPER, FastAPI API, acknowledge, scan. Mapper is reviewing the fixed FastAPI API station.')).toBeInTheDocument()
      expect(screen.getByText('MAPPER')).toBeInTheDocument()
    } finally {
      window.matchMedia = original
    }
  })

  it('keeps latest event context safe and has no tool, effect, or audio DOM', () => {
    const event = previewEvents('success').find((item) => item.type === 'verifier_a.call_recorded')!
    const { container } = render(<ArchitectureMap events={[event]} />)
    expect(screen.getByText('Verifier A (sequential)')).toBeInTheDocument()
    expect(screen.getByText('All agents are staged')).toBeInTheDocument()
    expect(screen.getByText('watch-only')).toBeInTheDocument()
    expect(screen.getByText('Role and authentication · Submissions')).toBeInTheDocument()
    expect(container.querySelector('[data-room-id="role-authentication"]')).toHaveClass('is-related')
    expect(container.querySelector('[data-effect-key]')).not.toBeInTheDocument()
    expect(container.querySelector('[data-agent-glyph]')).not.toBeInTheDocument()
    expect(container.querySelector('audio')).not.toBeInTheDocument()
    expect(container.querySelector('.architecture-effect')).not.toBeInTheDocument()
    expect(container.innerHTML).not.toMatch(/pickaxe|laser|<audio/i)
    expect(screen.queryByText('/submissions/mine')).not.toBeInTheDocument()
    expect(screen.queryByText('body-a1')).not.toBeInTheDocument()
  })

  it('keeps room emphasis on the active fixed cue while newer event context is accepted', () => {
    vi.useFakeTimers()
    const mapper = mapperEvent()
    const reset = previewEvents('success').find((event) => event.type === 'identity_reset.completed')!
    const { container, rerender } = render(<ArchitectureMap events={[]} />)
    rerender(<ArchitectureMap events={[mapper, reset]} generation={1} />)
    expect(container.querySelector('[data-agent-id="mapper"]')).toHaveAttribute('data-agent-state', 'walk')
    expect(container.querySelector('[data-room-id="fastapi-api"]')).toHaveClass('is-related')
    expect(container.querySelector('[data-room-id="sqlite-persistence"]')).not.toHaveClass('is-related')
  })
})
