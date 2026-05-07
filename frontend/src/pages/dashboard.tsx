import { useState, useCallback, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
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
    status: 'PENDING_REVIEW',
    marketplace_account_id: initialMarketplace ? Number(initialMarketplace) : '',
    search: '',
  })

  const { data: threadsData, isLoading, isError, refetch } = useThreads(filters)
  const { data: marketplaces = [] } = useMarketplaces()

  const threads = threadsData?.items ?? []

  const handleFiltersChange = useCallback((newFilters: ThreadFilters) => {
    setFilters(newFilters)
  }, [])

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
      />

      {/* Pagination info */}
      {threadsData && threadsData.total > threadsData.items.length && (
        <p className="text-center text-xs text-slate-400 dark:text-slate-500">
          Showing {threadsData.items.length} of {threadsData.total} threads.
          Refine your filters to narrow results.
        </p>
      )}
    </div>
  )
}
