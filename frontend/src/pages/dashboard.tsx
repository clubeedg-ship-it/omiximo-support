import { useState, useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { StatsBar } from '@/components/dashboard/stats-bar'
import { AlertsBanner } from '@/components/dashboard/alerts-banner'
import { ThreadFiltersBar } from '@/components/threads/thread-filters'
import { ThreadTable } from '@/components/threads/thread-table'
import { useThreads, useMarketplaces } from '@/hooks/use-threads'
import type { ThreadFilters } from '@/lib/types'

export function DashboardPage() {
  const [searchParams] = useSearchParams()
  const initialMarketplace = searchParams.get('marketplace')

  const [filters, setFilters] = useState<ThreadFilters>({
    risk_level: '',
    status: '',
    reply_state: '',
    marketplace_account_id: initialMarketplace ?? '',
    search: '',
  })
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [sortBy, setSortBy] = useState('last_activity_at')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  const effectiveFilters: ThreadFilters = { ...filters, sort_by: sortBy, sort_order: sortOrder }
  const { data: threadsData, isLoading, isError, refetch } = useThreads(effectiveFilters, page, pageSize)
  const { data: marketplaces = [] } = useMarketplaces()

  const threads = threadsData?.items ?? []
  const totalPages = threadsData ? Math.max(1, Math.ceil(threadsData.total / pageSize)) : 1

  const handleFiltersChange = useCallback((newFilters: ThreadFilters) => {
    setFilters(newFilters)
    setPage(1)
  }, [])

  const handleSort = useCallback((column: string) => {
    if (sortBy === column) {
      setSortOrder((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortBy(column)
      setSortOrder('asc')
    }
    setPage(1)
  }, [sortBy])

  const handleRefresh = useCallback(() => {
    void refetch()
  }, [refetch])

  // Auto-refresh every 60 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      void refetch()
    }, 60_000)
    return () => { clearInterval(interval) }
  }, [refetch])

  return (
    <div className="space-y-5">
      {/* Page heading */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">
            Support Queue
          </h1>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
            {threadsData
              ? `${threadsData.total} thread${threadsData.total !== 1 ? 's' : ''} total`
              : 'Loading...'}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={isLoading}
          aria-label="Refresh thread list"
        >
          <RefreshCw className={`mr-1.5 h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} aria-hidden="true" />
          Refresh
        </Button>
      </div>

      {/* Alerts */}
      <AlertsBanner />

      {/* Stats */}
      <StatsBar threads={threads} isLoading={isLoading} />

      {/* Filters */}
      <ThreadFiltersBar
        filters={filters}
        marketplaces={marketplaces}
        onChange={handleFiltersChange}
      />

      {/* Thread table */}
      <ThreadTable
        threads={threads}
        isLoading={isLoading}
        isError={isError}
        onRefresh={handleRefresh}
        sortBy={sortBy}
        sortOrder={sortOrder}
        onSort={handleSort}
      />

      {/* Pagination */}
      {threadsData && threadsData.total > 0 && (
        <nav className="flex flex-wrap items-center justify-between gap-4" aria-label="Pagination">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-slate-400">Rows per page:</span>
            <Select
              value={String(pageSize)}
              onValueChange={(v) => { setPageSize(Number(v)); setPage(1) }}
            >
              <SelectTrigger className="h-7 w-[70px] text-xs" aria-label="Rows per page">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="10">10</SelectItem>
                <SelectItem value="25">25</SelectItem>
                <SelectItem value="50">50</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <p className="text-xs text-slate-500 dark:text-slate-400 tabular-nums">
            Page {page} of {totalPages} ({threadsData.total} total)
          </p>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => { setPage((p) => Math.max(1, p - 1)) }}
              disabled={page === 1 || isLoading}
              aria-label="Previous page"
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => { setPage((p) => Math.min(totalPages, p + 1)) }}
              disabled={page >= totalPages || isLoading}
              aria-label="Next page"
            >
              Next
            </Button>
          </div>
        </nav>
      )}
    </div>
  )
}
