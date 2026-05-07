import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle, XCircle, Clock, Loader2 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useClassificationFlags, useResolveFlag } from '@/hooks/use-classification'
import type { ClassificationFlag, ClassificationFlagsParams } from '@/lib/types'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------
// Filter type
// ---------------------------------------------------------------------------

type FilterMode = 'all' | 'unresolved' | 'resolved'

// ---------------------------------------------------------------------------
// Row color coding helper
// ---------------------------------------------------------------------------

function rowClass(flag: ClassificationFlag): string {
  if (flag.resolution === 'accepted') {
    return 'bg-emerald-50 dark:bg-emerald-900/10'
  }
  if (flag.resolution === 'rejected') {
    return 'bg-rose-50 dark:bg-rose-900/10'
  }
  return 'bg-amber-50 dark:bg-amber-900/10'
}

// ---------------------------------------------------------------------------
// Resolution badge
// ---------------------------------------------------------------------------

function ResolutionBadge({ flag }: { flag: ClassificationFlag }) {
  if (flag.resolution === 'accepted') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300">
        <CheckCircle className="h-3 w-3" aria-hidden="true" />
        Accepted
      </span>
    )
  }
  if (flag.resolution === 'rejected') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-800 dark:bg-rose-900/30 dark:text-rose-300">
        <XCircle className="h-3 w-3" aria-hidden="true" />
        Rejected
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
      <Clock className="h-3 w-3" aria-hidden="true" />
      Pending
    </span>
  )
}

// ---------------------------------------------------------------------------
// Diff cell: shows original → correct if they differ
// ---------------------------------------------------------------------------

function DiffCell({ original, correct }: { original: string; correct: string }) {
  if (original === correct) {
    return <span className="text-slate-600 dark:text-slate-400">{original}</span>
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      <span className="line-through text-slate-400 dark:text-slate-500">{original}</span>
      <span className="text-slate-300 dark:text-slate-600" aria-hidden="true">→</span>
      <span className="font-medium text-slate-900 dark:text-slate-100">{correct}</span>
    </span>
  )
}

// ---------------------------------------------------------------------------
// Flag row actions
// ---------------------------------------------------------------------------

interface FlagRowActionsProps {
  flag: ClassificationFlag
  isLoading: boolean
  onAccept: () => void
  onReject: () => void
}

function FlagRowActions({ flag, isLoading, onAccept, onReject }: FlagRowActionsProps) {
  if (flag.resolution !== null) return null

  return (
    <div className="flex items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        onClick={onAccept}
        disabled={isLoading}
        className="h-7 border-emerald-300 text-emerald-700 hover:bg-emerald-50 hover:text-emerald-800 dark:border-emerald-700 dark:text-emerald-400 dark:hover:bg-emerald-900/20"
        aria-label="Accept flag"
      >
        {isLoading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : (
          <CheckCircle className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        <span className="ml-1">Accept</span>
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={onReject}
        disabled={isLoading}
        className="h-7 border-rose-300 text-rose-700 hover:bg-rose-50 hover:text-rose-800 dark:border-rose-700 dark:text-rose-400 dark:hover:bg-rose-900/20"
        aria-label="Reject flag"
      >
        {isLoading ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
        ) : (
          <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        <span className="ml-1">Reject</span>
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export function ClassificationPage() {
  const [filterMode, setFilterMode] = useState<FilterMode>('unresolved')
  const [page, setPage] = useState(1)
  const PAGE_SIZE = 25

  const queryParams: ClassificationFlagsParams = {
    ...(filterMode === 'unresolved' ? { reviewed: false } : {}),
    ...(filterMode === 'resolved' ? { reviewed: true } : {}),
    page,
    page_size: PAGE_SIZE,
  }

  const { data, isLoading, isError } = useClassificationFlags(queryParams)
  const resolveMutation = useResolveFlag()

  const flags = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)

  const handleResolve = (flagId: string, resolution: 'accepted' | 'rejected') => {
    resolveMutation.mutate({
      flagId,
      data: { resolution, actor: 'admin@omiximo.nl' },
    })
  }

  return (
    <div className="space-y-6">
      {/* Page heading */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">
            Classification Tuning
          </h1>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
            Review and resolve misclassification flags to improve accuracy
          </p>
        </div>

        <Select
          value={filterMode}
          onValueChange={(v) => {
            setFilterMode(v as FilterMode)
            setPage(1)
          }}
        >
          <SelectTrigger className="h-8 w-[160px] text-xs" aria-label="Filter flags by resolution status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="unresolved">Unresolved only</SelectItem>
            <SelectItem value="resolved">Resolved only</SelectItem>
            <SelectItem value="all">All flags</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Table card */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-slate-700 dark:text-slate-300">
            {isLoading ? 'Loading...' : `${total} flag${total !== 1 ? 's' : ''}`}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && (
            <div className="flex items-center justify-center py-16" role="status" aria-label="Loading flags">
              <Loader2 className="h-6 w-6 animate-spin text-slate-400" aria-hidden="true" />
            </div>
          )}

          {isError && (
            <div className="flex items-center justify-center py-16">
              <p className="text-sm text-rose-600 dark:text-rose-400">
                Failed to load classification flags. Please try again.
              </p>
            </div>
          )}

          {!isLoading && !isError && flags.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <CheckCircle className="h-8 w-8 text-slate-300 dark:text-slate-600 mb-3" aria-hidden="true" />
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400">
                No flags found
              </p>
              <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
                {filterMode === 'unresolved'
                  ? 'All flags have been resolved.'
                  : 'No classification flags have been submitted yet.'}
              </p>
            </div>
          )}

          {!isLoading && !isError && flags.length > 0 && (
            <div className="overflow-x-auto">
              <table
                className="w-full text-sm"
                aria-label="Classification flags"
              >
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-700">
                    <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      Thread
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      Category
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      Risk Level
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      Language
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400">
                      Reason
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      Actor
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      Status
                    </th>
                    <th scope="col" className="px-4 py-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 whitespace-nowrap">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {flags.map((flag) => {
                    const isResolvingThisFlag =
                      resolveMutation.isPending &&
                      resolveMutation.variables?.flagId === flag.id

                    return (
                      <tr
                        key={flag.id}
                        className={cn(
                          'border-b border-slate-100 dark:border-slate-800 transition-colors',
                          rowClass(flag),
                        )}
                      >
                        {/* Thread link */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <Link
                            to={`/review/${flag.thread_id}`}
                            className="font-mono text-xs text-sky-600 hover:text-sky-700 hover:underline dark:text-sky-400 dark:hover:text-sky-300"
                            aria-label={`Open thread ${flag.thread_id}`}
                          >
                            #{flag.thread_id}
                          </Link>
                        </td>

                        {/* Category diff */}
                        <td className="px-4 py-3">
                          <DiffCell
                            original={flag.original_category}
                            correct={flag.correct_category}
                          />
                        </td>

                        {/* Risk level diff */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <DiffCell
                            original={flag.original_risk_level}
                            correct={flag.correct_risk_level}
                          />
                        </td>

                        {/* Language diff */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <DiffCell
                            original={flag.original_language.toUpperCase()}
                            correct={flag.correct_language.toUpperCase()}
                          />
                        </td>

                        {/* Reason */}
                        <td className="px-4 py-3 max-w-[240px]">
                          <p
                            className="text-xs text-slate-600 dark:text-slate-400 line-clamp-2"
                            title={flag.reason}
                          >
                            {flag.reason}
                          </p>
                        </td>

                        {/* Actor */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className="text-xs text-slate-600 dark:text-slate-400">
                            {flag.actor}
                          </span>
                        </td>

                        {/* Resolution badge */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <ResolutionBadge flag={flag} />
                        </td>

                        {/* Actions */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <FlagRowActions
                            flag={flag}
                            isLoading={isResolvingThisFlag}
                            onAccept={() => { handleResolve(flag.id, 'accepted') }}
                            onReject={() => { handleResolve(flag.id, 'rejected') }}
                          />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {totalPages > 1 && (
        <nav
          className="flex items-center justify-between"
          aria-label="Pagination"
        >
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Page {page} of {totalPages} ({total} total)
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
              disabled={page === totalPages || isLoading}
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
