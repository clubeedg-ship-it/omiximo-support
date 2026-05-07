import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ThreadFiltersBar } from '@/components/threads/thread-filters'
import type { ThreadFilters, MarketplaceAccount } from '@/lib/types'

const defaultFilters: ThreadFilters = {
  risk_level: '',
  status: '',
  marketplace_account_id: '',
  search: '',
}

const mockMarketplaces: MarketplaceAccount[] = [
  { id: '00000000-0000-0000-0000-000000000001', marketplace: 'MediaMarkt', shop_id: 'mm-1', base_url: '', sla_hours: 24, template_set: 'default', is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: '00000000-0000-0000-0000-000000000002', marketplace: 'Boulanger', shop_id: 'bl-1', base_url: '', sla_hours: 48, template_set: 'default', is_active: true, created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
]

describe('ThreadFiltersBar', () => {
  it('renders search input', () => {
    render(
      <ThreadFiltersBar
        filters={defaultFilters}
        marketplaces={[]}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByPlaceholderText(/search by order/i)).toBeInTheDocument()
  })

  it('calls onChange when search input changes', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(
      <ThreadFiltersBar
        filters={defaultFilters}
        marketplaces={[]}
        onChange={onChange}
      />,
    )
    await user.type(screen.getByPlaceholderText(/search by order/i), 'A')
    expect(onChange).toHaveBeenCalled()
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0] as ThreadFilters
    // The onChange receives the full updated filter object each keystroke
    expect(lastCall).toHaveProperty('search')
    expect(typeof lastCall.search).toBe('string')
  })

  it('renders marketplace dropdown when marketplaces provided', () => {
    render(
      <ThreadFiltersBar
        filters={defaultFilters}
        marketplaces={mockMarketplaces}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByLabelText('Filter by marketplace')).toBeInTheDocument()
  })

  it('does not render marketplace dropdown when no marketplaces', () => {
    render(
      <ThreadFiltersBar
        filters={defaultFilters}
        marketplaces={[]}
        onChange={vi.fn()}
      />,
    )
    expect(screen.queryByLabelText('Filter by marketplace')).not.toBeInTheDocument()
  })
})
