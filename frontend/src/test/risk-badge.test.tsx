import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RiskBadge } from '@/components/threads/risk-badge'

describe('RiskBadge', () => {
  it('renders "Green" for GREEN risk level', () => {
    render(<RiskBadge risk="GREEN" />)
    expect(screen.getByText('Green')).toBeInTheDocument()
  })

  it('renders "Orange" for ORANGE risk level', () => {
    render(<RiskBadge risk="ORANGE" />)
    expect(screen.getByText('Orange')).toBeInTheDocument()
  })

  it('renders "Red" for RED risk level', () => {
    render(<RiskBadge risk="RED" />)
    expect(screen.getByText('Red')).toBeInTheDocument()
  })

  it('applies custom className', () => {
    const { container } = render(<RiskBadge risk="GREEN" className="test-class" />)
    expect(container.firstChild).toHaveClass('test-class')
  })
})
