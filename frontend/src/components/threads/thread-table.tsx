import { useNavigate } from 'react-router-dom'
import { ArrowRight, AlertCircle, RefreshCw, CheckCircle, ArrowUp, ArrowDown, ArrowUpDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { RiskBadge } from './risk-badge'
import { StatusBadge } from './status-badge'
import { ReplyStateBadge } from './reply-state-badge'
import type { Thread } from '@/lib/types'
import {
  formatRelativeTime,
  truncate,
  stripHtml,
  calculateSlaStatus,
  getCategoryLabel,
  cn,
} from '@/lib/utils'

interface ThreadTableProps {
  threads: Thread[]
  isLoading: boolean
  isError: boolean
  onRefresh: () => void
  sortBy?: string
  sortOrder?: 'asc' | 'desc'
  onSort?: (column: string) => void
}

function RepliedHint() {
  return (
    <span className="text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
      <CheckCircle className="h-3 w-3" aria-hidden="true" />
      Replied
    </span>
  )
}

function SlaCell({ thread }: { thread: Thread }) {
  const sla = calculateSlaStatus(
    thread.created_at,
    thread.response_deadline,
    thread.marketplace_account?.sla_hours ?? 24,
  )

  const isReplied = thread.status !== 'PENDING_REVIEW'

  if (sla.isHistorical) {
    return (
      <div className="flex flex-col gap-1">
        <Badge variant="slate">Historical</Badge>
        {isReplied && <RepliedHint />}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <span
        className={cn(
          'text-xs font-medium',
          sla.urgency === 'overdue' && 'text-rose-600 dark:text-rose-400',
          sla.urgency === 'critical' && 'text-rose-500 dark:text-rose-400',
          sla.urgency === 'warning' && 'text-amber-600 dark:text-amber-400',
          sla.urgency === 'normal' && 'text-slate-500 dark:text-slate-400',
        )}
      >
        {sla.label}
      </span>
      {isReplied ? (
        <RepliedHint />
      ) : (
        <div className="h-1 w-16 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden">
          <div
            className={cn(
              'h-full rounded-full transition-all',
              sla.urgency === 'overdue' && 'bg-rose-500',
              sla.urgency === 'critical' && 'bg-rose-400',
              sla.urgency === 'warning' && 'bg-amber-400',
              sla.urgency === 'normal' && 'bg-emerald-400',
            )}
            style={{ width: `${sla.percentage}%` }}
            role="progressbar"
            aria-valuenow={sla.percentage}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`SLA progress: ${sla.label}`}
          />
        </div>
      )}
    </div>
  )
}

function SortIcon({ column, sortBy, sortOrder }: { column: string; sortBy?: string; sortOrder?: 'asc' | 'desc' }) {
  if (sortBy !== column) {
    return <ArrowUpDown className="h-3 w-3 opacity-0 group-hover:opacity-50 transition-opacity" aria-hidden="true" />
  }
  return sortOrder === 'asc'
    ? <ArrowUp className="h-3 w-3" aria-hidden="true" />
    : <ArrowDown className="h-3 w-3" aria-hidden="true" />
}

export function ThreadTable({ threads, isLoading, isError, onRefresh, sortBy, sortOrder, onSort }: ThreadTableProps) {
  const navigate = useNavigate()

  if (isLoading) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
        <div className="p-8 text-center">
          <RefreshCw className="mx-auto mb-3 h-6 w-6 animate-spin text-slate-400" />
          <p className="text-sm text-slate-500 dark:text-slate-400">Loading threads...</p>
        </div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-lg border border-rose-200 bg-rose-50 dark:border-rose-800 dark:bg-rose-900/20">
        <div className="p-8 text-center">
          <AlertCircle className="mx-auto mb-3 h-6 w-6 text-rose-500" />
          <p className="mb-4 text-sm text-rose-700 dark:text-rose-300">
            Failed to load threads. Check your API connection.
          </p>
          <Button variant="outline" size="sm" onClick={onRefresh}>
            <RefreshCw className="mr-2 h-4 w-4" />
            Retry
          </Button>
        </div>
      </div>
    )
  }

  if (threads.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
        <div className="p-12 text-center">
          <p className="text-sm text-slate-500 dark:text-slate-400">
            No threads match your current filters.
          </p>
        </div>
      </div>
    )
  }

  const sortable = (label: string, column: string) => (
    <button
      type="button"
      className="inline-flex items-center gap-1 group"
      onClick={() => onSort?.(column)}
      aria-label={`Sort by ${label}`}
    >
      {label}
      <SortIcon column={column} sortBy={sortBy} sortOrder={sortOrder} />
    </button>
  )

  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden dark:border-slate-700 dark:bg-slate-900">
      <div className="overflow-x-auto">
        <table className="w-full text-sm" role="table" aria-label="Support threads">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50">
              <th className="px-4 py-3 text-left font-medium text-slate-600 dark:text-slate-400 whitespace-nowrap">
                {sortable('SLA', 'response_deadline')}
              </th>
              <th className="px-4 py-3 text-left font-medium text-slate-600 dark:text-slate-400 whitespace-nowrap">
                {sortable('Last activity', 'last_activity_at')}
              </th>
              <th className="px-4 py-3 text-left font-medium text-slate-600 dark:text-slate-400 whitespace-nowrap">
                Marketplace
              </th>
              <th className="px-4 py-3 text-left font-medium text-slate-600 dark:text-slate-400 whitespace-nowrap">
                {sortable('Category', 'category')}
              </th>
              <th className="px-4 py-3 text-left font-medium text-slate-600 dark:text-slate-400 whitespace-nowrap">
                {sortable('Risk', 'risk_level')}
              </th>
              <th className="px-4 py-3 text-left font-medium text-slate-600 dark:text-slate-400 whitespace-nowrap">
                {sortable('Status', 'status')}
              </th>
              <th className="px-4 py-3 text-left font-medium text-slate-600 dark:text-slate-400 whitespace-nowrap">
                {sortable('Reply', 'reply_state')}
              </th>
              <th className="px-4 py-3 text-left font-medium text-slate-600 dark:text-slate-400">
                Message
              </th>
              <th className="px-4 py-3 text-right font-medium text-slate-600 dark:text-slate-400 whitespace-nowrap">
                Action
              </th>
            </tr>
          </thead>
          <tbody>
            {threads.map((thread) => (
              <tr
                key={thread.id}
                className="border-b border-slate-100 hover:bg-slate-50 transition-colors cursor-pointer dark:border-slate-800 dark:hover:bg-slate-800/50"
                onClick={() => { void navigate(`/review/${thread.id}`) }}
                tabIndex={0}
                role="row"
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    void navigate(`/review/${thread.id}`)
                  }
                }}
                aria-label={`Thread ${thread.mirakl_order_id}: ${thread.risk_level} risk`}
              >
                <td className="px-4 py-3">
                  <SlaCell thread={thread} />
                </td>
                <td className="px-4 py-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                  {formatRelativeTime(thread.last_activity_at ?? thread.created_at)}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  <span className="font-medium text-slate-800 dark:text-slate-200">
                    {thread.marketplace_name ?? `Account #${thread.marketplace_account_id}`}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-600 dark:text-slate-400 whitespace-nowrap">
                  {thread.category ? getCategoryLabel(thread.category) : '—'}
                </td>
                <td className="px-4 py-3">
                  <RiskBadge risk={thread.risk_level} />
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={thread.status} />
                </td>
                <td className="px-4 py-3">
                  <ReplyStateBadge state={thread.reply_state} />
                </td>
                <td className="px-4 py-3 max-w-sm">
                  <div className="flex items-start gap-2">
                    <p className="text-slate-600 dark:text-slate-400 text-xs leading-relaxed">
                      {thread.message_summary ? truncate(thread.message_summary, 90) : truncate(stripHtml(thread.customer_message), 90)}
                    </p>
                    {thread.message_count !== undefined && thread.message_count > 1 && (
                      <span
                        className="shrink-0 inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                        title={`${thread.message_count} messages in this thread`}
                        aria-label={`${thread.message_count} messages`}
                      >
                        {thread.message_count}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3 text-right">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation()
                      void navigate(`/review/${thread.id}`)
                    }}
                    aria-label={`Review thread ${thread.mirakl_order_id}`}
                  >
                    Review
                    <ArrowRight className="ml-1 h-3.5 w-3.5" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
