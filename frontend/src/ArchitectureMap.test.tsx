import { StrictMode } from 'react'
import { act, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ArchitectureMap } from './ArchitectureMap'
import { previewEvents } from './fixtures'

const mapperEvent = () => previewEvents('success').find((event) => event.type === 'mapper.activated')!

let createdAudio: TestAudio[] = []

class TestAudio {
  src: string
  volume = 0
  currentTime = 0
  preload = ''
  play = vi.fn()
  pause = vi.fn()

  constructor(src: string) {
    this.src = src
    createdAudio.push(this)
  }
}

beforeEach(() => {
  createdAudio = []
  vi.stubGlobal('Audio', TestAudio)
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

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
      expect(screen.getByText('MAPPER, FastAPI API, acknowledge, scan. Cycle 1 of 2. Mapper is reviewing the fixed FastAPI API station.')).toBeInTheDocument()
      expect(screen.getByText('MAPPER')).toBeInTheDocument()
    } finally {
      window.matchMedia = original
    }
  })

  it('keeps latest event context safe before a user-initiated replay', () => {
    const event = previewEvents('success').find((item) => item.type === 'verifier_a.call_recorded')!
    const { container } = render(<ArchitectureMap events={[event]} />)
    expect(screen.getByText('Verifier A (sequential)')).toBeInTheDocument()
    expect(screen.getByText('All agents are staged')).toBeInTheDocument()
    expect(screen.getByText('watch-only')).toBeInTheDocument()
    expect(screen.getByText('Role and authentication · Submissions')).toBeInTheDocument()
    expect(container.querySelector('[data-room-id="role-authentication"]')).toHaveClass('is-related')
    expect(container.querySelector('[data-effect-key]')).not.toBeInTheDocument()
    expect(container.querySelector('audio')).not.toBeInTheDocument()
    expect(container.querySelector('.architecture-tool-effect')).not.toBeInTheDocument()
    expect(screen.queryByText('/submissions/mine')).not.toBeInTheDocument()
    expect(screen.queryByText('body-a1')).not.toBeInTheDocument()
  })

  it('uses fixed recorded speed, renders a compact safe tool cycle, and keeps tool bounds clipped', () => {
    vi.useFakeTimers()
    const verifier = previewEvents('success').find((event) => event.type === 'verifier_a.call_recorded')!
    const { container, rerender } = render(<ArchitectureMap events={[]} recordedReplay />)
    rerender(<ArchitectureMap events={[verifier]} generation={1} recordedReplay />)
    const firstLeg = container.querySelector('[data-agent-id="verifier-a"] animateTransform')!
    expect(Number.parseFloat(firstLeg.getAttribute('dur')!)).toBeCloseTo(1114.3, 1)
    act(() => { vi.advanceTimersByTime(2800) })
    const effect = container.querySelector('[data-tool-effect="pickaxe"]')!
    expect(effect).toHaveAttribute('data-effect-cycle', '1')
    const viewport = effect.querySelector('.architecture-tool-viewport')!
    expect(viewport).toHaveAttribute('width', '64')
    expect(viewport).toHaveAttribute('height', '56')
    expect(viewport).toHaveAttribute('overflow', 'hidden')
    expect(effect).toHaveClass('is-cycling')
    act(() => { vi.advanceTimersByTime(720) })
    expect(container.querySelector('[data-tool-effect="pickaxe"] .architecture-tool-viewport')).not.toBe(viewport)
  })

  it('does not create replay audio before a gesture, respects sound off, and cancels sound on restart', () => {
    vi.useFakeTimers()
    const { rerender } = render(<ArchitectureMap events={[mapperEvent()]} recordedReplay />)
    expect(createdAudio).toHaveLength(0)

    rerender(<ArchitectureMap events={[]} generation={1} soundEnabled={false} recordedReplay />)
    rerender(<ArchitectureMap events={[mapperEvent()]} generation={1} soundEnabled={false} recordedReplay />)
    expect(createdAudio).toHaveLength(0)

    rerender(<ArchitectureMap events={[]} generation={2} soundEnabled recordedReplay />)
    rerender(<ArchitectureMap events={[mapperEvent()]} generation={2} soundEnabled recordedReplay />)
    expect(createdAudio[0]).toMatchObject({ src: '/map/audio/footsteps.wav' })
    rerender(<ArchitectureMap events={[]} generation={3} soundEnabled recordedReplay />)
    expect(createdAudio[0].pause).toHaveBeenCalled()
  })

  it('keeps user-armed replay audio available after Strict Mode effect replay', async () => {
    const { container, rerender } = render(<StrictMode><ArchitectureMap events={[]} recordedReplay /></StrictMode>)
    await act(async () => { await Promise.resolve() })
    rerender(<StrictMode><ArchitectureMap events={[]} generation={1} recordedReplay /></StrictMode>)
    rerender(<StrictMode><ArchitectureMap events={[mapperEvent()]} generation={1} recordedReplay /></StrictMode>)
    await act(async () => { await Promise.resolve() })
    expect(container.querySelector('[data-agent-id="mapper"]')).toHaveAttribute('data-agent-state', 'walk')
    expect(createdAudio[0]).toMatchObject({ src: '/map/audio/footsteps.wav' })
  })

  it('stops choreography at failure and permits only one final failure cue', () => {
    vi.useFakeTimers()
    const failureEvents = previewEvents('failure')
    const mapper = failureEvents.find((event) => event.type === 'mapper.activated')!
    const terminal = failureEvents.find((event) => event.type === 'session.failed')!
    const { container, rerender } = render(<ArchitectureMap events={[]} recordedReplay />)

    rerender(<ArchitectureMap events={[]} generation={1} recordedReplay />)
    rerender(<ArchitectureMap events={[mapper]} generation={1} recordedReplay />)
    expect(createdAudio[0]).toMatchObject({ src: '/map/audio/footsteps.wav' })

    rerender(<ArchitectureMap events={[mapper, terminal]} generation={1} recordedReplay />)
    expect(container.querySelector('[data-agent-id="mapper"]')).toHaveAttribute('data-agent-state', 'docked')
    expect(container.querySelector('[data-tool-effect]')).not.toBeInTheDocument()
    expect(createdAudio.at(-1)).toMatchObject({ src: '/map/audio/failure.wav' })
    const cueCount = createdAudio.length
    act(() => { vi.runAllTimers() })
    expect(createdAudio).toHaveLength(cueCount)
  })

  it('keeps reduced-motion tool icon static while preserving cycle status', () => {
    vi.useFakeTimers()
    const original = window.matchMedia
    window.matchMedia = vi.fn().mockReturnValue({ matches: true, addEventListener: vi.fn(), removeEventListener: vi.fn() })
    try {
      const verifier = previewEvents('success').find((event) => event.type === 'verifier_b.call_recorded')!
      const verifierA = previewEvents('success').find((event) => event.type === 'verifier_a.call_recorded')!
      const { container, rerender } = render(<ArchitectureMap events={[]} />)
      rerender(<ArchitectureMap events={[verifierA, verifier]} generation={1} />)
      act(() => { vi.advanceTimersByTime(2400) })
      const effect = container.querySelector('[data-tool-effect="beam"]')
      expect(effect).toBeInTheDocument()
      expect(effect).not.toHaveClass('is-cycling')
      expect(container.querySelector('animateTransform')).not.toBeInTheDocument()
    } finally {
      window.matchMedia = original
    }
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
