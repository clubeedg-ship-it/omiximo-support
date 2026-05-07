import { useCallback } from 'react'
import { Search } from 'lucide-react'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { ThreadFilters, RiskLevel, ThreadStatus, MarketplaceAccount } from '@/lib/types'

interface ThreadFiltersProps {
  filters: ThreadFilters
  marketplaces: MarketplaceAccount[]
  onChange: (filters: ThreadFilters) => void
}

export function ThreadFiltersBar({ filters, marketplaces, onChange }: ThreadFiltersProps) {
  const handleRiskChange = useCallback(
    (value: string) => {
      onChange({ ...filters, risk_level: value === 'ALL' ? '' : (value as RiskLevel) })
    },
    [filters, onChange],
  )

  const handleStatusChange = useCallback(
    (value: string) => {
      onChange({ ...filters, status: value === 'ALL' ? '' : (value as ThreadStatus) })
    },
    [filters, onChange],
  )

  const handleMarketplaceChange = useCallback(
    (value: string) => {
      onChange({ ...filters, marketplace_account_id: value === 'ALL' ? '' : value })
    },
    [filters, onChange],
  )

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange({ ...filters, search: e.target.value })
    },
    [filters, onChange],
  )

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
      <div className="relative flex-1 min-w-[200px]">
        <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <Input
          placeholder="Search by order ID or message..."
          value={filters.search ?? ''}
          onChange={handleSearchChange}
          className="pl-9"
          aria-label="Search threads"
        />
      </div>

      <Select
        value={filters.risk_level ?? 'ALL'}
        onValueChange={handleRiskChange}
      >
        <SelectTrigger className="w-[140px]" aria-label="Filter by risk level">
          <SelectValue placeholder="Risk level" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="ALL">All risk levels</SelectItem>
          <SelectItem value="GREEN">Green</SelectItem>
          <SelectItem value="ORANGE">Orange</SelectItem>
          <SelectItem value="RED">Red</SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={filters.status ?? 'ALL'}
        onValueChange={handleStatusChange}
      >
        <SelectTrigger className="w-[160px]" aria-label="Filter by status">
          <SelectValue placeholder="Status" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="ALL">All statuses</SelectItem>
          <SelectItem value="PENDING_REVIEW">Pending Review</SelectItem>
          <SelectItem value="APPROVED">Approved</SelectItem>
          <SelectItem value="SENT_AUTO">Sent (Auto)</SelectItem>
          <SelectItem value="ESCALATED">Escalated</SelectItem>
          <SelectItem value="FAILED">Failed</SelectItem>
        </SelectContent>
      </Select>

      {marketplaces.length > 0 && (
        <Select
          value={filters.marketplace_account_id ? filters.marketplace_account_id : 'ALL'}
          onValueChange={handleMarketplaceChange}
        >
          <SelectTrigger className="w-[160px]" aria-label="Filter by marketplace">
            <SelectValue placeholder="Marketplace" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All marketplaces</SelectItem>
            {marketplaces.map((mp) => (
              <SelectItem key={mp.id} value={mp.id}>
                {mp.marketplace}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  )
}
