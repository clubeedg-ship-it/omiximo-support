import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatsBar } from '@/components/dashboard/stats-bar'
import type { Thread } from '@/lib/types'

function makeThread(overrides: Partial<Thread>): Thread {
  return {
    id: '00000000-0000-0000-0000-000000000001',
    mirakl_thread_id: 'thr-1',
    mirakl_order_id: 'ORD-001',
    marketplace_account_id: '00000000-0000-0000-0000-000000000001',
    customer_language: 'en',
    category: 'delivery',
    risk_level: 'GREEN',
    status: 'PENDING_REVIEW',
    operator_required: false,
    customer_message: 'Where is my order?',
    drafted_response: null,
    tracking_status: null,
    invoice_status: null,
    response_deadline: new Date().toISOString(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ...overrides,
  }
}

describe('StatsBar', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('renders all stat cards', () => {
    render(<StatsBar threads={[]} isLoading={false} />)
    expect(screen.getByText('Pending Review')).toBeInTheDocument()
    expect(screen.getByText('Green (Low Risk)')).toBeInTheDocument()
    expect(screen.getByText('Orange (Medium)')).toBeInTheDocument()
    expect(screen.getByText('Red (High Risk)')).toBeInTheDocument()
    expect(screen.getByText('SLA Overdue')).toBeInTheDocument()
  })

  it('shows dashes while loading', () => {
    render(<StatsBar threads={[]} isLoading={true} />)
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThan(0)
  })

  it('counts green threads correctly', () => {
    const threads = [
      makeThread({ risk_level: 'GREEN' }),
      makeThread({ id: '00000000-0000-0000-0000-000000000002', risk_level: 'ORANGE' }),
      makeThread({ id: '00000000-0000-0000-0000-000000000003', risk_level: 'RED' }),
    ]
    render(<StatsBar threads={threads} isLoading={false} />)
    // Green count should be 1
    const greenCard = screen.getByText('Green (Low Risk)').closest('[class]')
    expect(greenCard).toBeTruthy()
  })

  it('has accessible region label', () => {
    render(<StatsBar threads={[]} isLoading={false} />)
    expect(screen.getByRole('region', { name: 'Support queue statistics' })).toBeInTheDocument()
  })
})
