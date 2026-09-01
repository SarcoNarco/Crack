import { render, screen } from '@testing-library/react'
import { ArchitectureMap } from './ArchitectureMap'
import { previewEvents } from './fixtures'

describe('architecture floor presentation', () => {
  it('renders six labelled rooms, nine fixed corridors, and four staged concepts', () => {
    const { container } = render(<ArchitectureMap events={[]} />)
    expect(screen.getByRole('img', { name: /Static school portal operations floor/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'No presentation event received' })).toBeInTheDocument()
    expect(container.querySelector('.architecture-map')).toHaveAttribute('viewBox', '0 0 960 540')
    expect(screen.getByRole('region', { name: 'Scrollable operations floor' })).toHaveAttribute('tabindex', '0')
    expect(container.querySelector('.architecture-environment-image')).toHaveAttribute('href', '/map/crack-operations-floor.png')
    expect(container.querySelectorAll('[data-room-id]')).toHaveLength(6)
    expect(container.querySelectorAll('[data-corridor-id]')).toHaveLength(9)
    expect(container.querySelectorAll('[data-agent-concept="static"]')).toHaveLength(4)
    expect(screen.getByText('STAGING DOCK')).toBeInTheDocument()
    expect(screen.getByText('MAPPER')).toBeInTheDocument()
    expect(screen.getByText('AUTH TESTER')).toBeInTheDocument()
    expect(screen.getByText('VERIFIER A')).toBeInTheDocument()
    expect(screen.getByText('VERIFIER B')).toBeInTheDocument()
    expect(container.querySelector('[data-agent-id="mapper"] .architecture-agent-sprite')).toHaveAttribute('href', '/map/agents/mapper.png')
    expect(container.querySelectorAll('.architecture-agent-sprite')).toHaveLength(4)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('keeps latest-event context safe while highlighting related rooms without effect glyphs', () => {
    const event = previewEvents('success').find((item) => item.type === 'verifier_a.call_recorded')!
    const { container } = render(<ArchitectureMap events={[event]} />)
    expect(screen.getByText('Verifier A (sequential)')).toBeInTheDocument()
    expect(screen.getByText('Reserved for later choreography')).toBeInTheDocument()
    expect(screen.getByText('static presentation')).toBeInTheDocument()
    expect(screen.getByText('Role and authentication · Submissions')).toBeInTheDocument()
    expect(container.querySelector('[data-room-id="role-authentication"]')).toHaveClass('is-related')
    expect(container.querySelector('[data-room-id="submissions"]')).toHaveClass('is-related')
    expect(container.querySelector('[data-effect-key]')).not.toBeInTheDocument()
    expect(container.querySelector('[data-agent-glyph]')).not.toBeInTheDocument()
    expect(container.querySelector('.architecture-effect')).not.toBeInTheDocument()
    expect(screen.queryByText('/submissions/mine')).not.toBeInTheDocument()
    expect(screen.queryByText('body-a1')).not.toBeInTheDocument()
  })

  it('shows outside-target events as a static, watch-only context', () => {
    const event = previewEvents('success').find((item) => item.type === 'consensus.completed')!
    render(<ArchitectureMap events={[event]} />)
    expect(screen.getByText('Code-owned consensus')).toBeInTheDocument()
    expect(screen.getByText('Outside this static target map')).toBeInTheDocument()
    expect(screen.getByText('Reserved for later choreography')).toBeInTheDocument()
  })
})
