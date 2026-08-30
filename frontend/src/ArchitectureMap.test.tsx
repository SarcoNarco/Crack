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

  it('shows only safe labels, actor, event headline, and component relation', () => {
    const event = previewEvents('success').find((item) => item.type === 'verifier_a.call_recorded')!
    const { container } = render(<ArchitectureMap events={[event]} />)
    expect(screen.getByText('Verifier A (sequential)')).toBeInTheDocument()
    expect(screen.getByText('Role and authentication · Submissions')).toBeInTheDocument()
    expect(container.querySelector('[data-node-id="role-authentication"]')).toHaveClass('is-related')
    expect(container.querySelector('[data-node-id="submissions"]')).toHaveClass('is-related')
    expect(screen.queryByText('/submissions/mine')).not.toBeInTheDocument()
    expect(screen.queryByText('body-a1')).not.toBeInTheDocument()
  })
})
