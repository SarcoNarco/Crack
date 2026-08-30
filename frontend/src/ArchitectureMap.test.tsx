import { render, screen } from '@testing-library/react'
import { ArchitectureMap } from './ArchitectureMap'
import { previewEvents } from './fixtures'

describe('architecture map presentation', () => {
  it('renders a labelled static SVG and an honest waiting state', () => {
    const { container } = render(<ArchitectureMap events={[]} />)
    expect(screen.getByRole('img', { name: /Static school portal architecture map/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'No presentation event received' })).toBeInTheDocument()
    expect(container.querySelectorAll('[data-node-id]')).toHaveLength(6)
    expect(container.querySelectorAll('[data-edge-id]')).toHaveLength(9)
  })

  it('shows one labelled presentation-only actor tool, state, and safe component relation', () => {
    const event = previewEvents('success').find((item) => item.type === 'verifier_a.call_recorded')!
    const { container } = render(<ArchitectureMap events={[event]} />)
    expect(screen.getByText('Verifier A (sequential)')).toBeInTheDocument()
    expect(screen.getByText('Verifier A pickaxe')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
    expect(screen.getByText('presentation-only', { exact: true })).toBeInTheDocument()
    expect(screen.getByText('Role and authentication · Submissions')).toBeInTheDocument()
    expect(container.querySelector('[data-node-id="role-authentication"]')).toHaveClass('is-related')
    expect(container.querySelector('[data-node-id="submissions"]')).toHaveClass('is-related')
    expect(container.querySelectorAll('[data-effect-key]')).toHaveLength(1)
    expect(container.querySelector('[data-effect-kind="pickaxe"]')).toBeInTheDocument()
    expect(container.querySelector('[data-effect-kind="pickaxe"] [data-agent-glyph]')).toBeInTheDocument()
    expect(screen.queryByText('/submissions/mine')).not.toBeInTheDocument()
    expect(screen.queryByText('body-a1')).not.toBeInTheDocument()
  })

  it('uses no target tool marker when latest actor is outside the static map', () => {
    const event = previewEvents('success').find((item) => item.type === 'consensus.completed')!
    const { container } = render(<ArchitectureMap events={[event]} />)
    expect(screen.getByText('Code-owned consensus')).toBeInTheDocument()
    expect(screen.getByText('Static actor marker')).toBeInTheDocument()
    expect(container.querySelector('[data-effect-key]')).not.toBeInTheDocument()
  })
})
