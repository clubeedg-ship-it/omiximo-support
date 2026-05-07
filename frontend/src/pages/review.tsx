import { useParams, useNavigate } from 'react-router-dom'
import { AlertCircle, RefreshCw, ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ReviewPane } from '@/components/review/review-pane'
import { useThread } from '@/hooks/use-thread'

export function ReviewPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const threadId = id ?? null

  const { data: thread, isLoading, isError, error, refetch } = useThread(threadId)

  if (!id) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <AlertCircle className="mb-4 h-10 w-10 text-rose-400" aria-hidden="true" />
        <h2 className="mb-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
          Invalid Thread ID
        </h2>
        <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
          The URL does not contain a valid thread identifier.
        </p>
        <Button variant="outline" onClick={() => { void navigate('/') }}>
          <ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />
          Back to Dashboard
        </Button>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <RefreshCw className="mb-4 h-8 w-8 animate-spin text-slate-400" aria-hidden="true" />
        <p className="text-sm text-slate-500 dark:text-slate-400">Loading thread...</p>
      </div>
    )
  }

  if (isError || !thread) {
    const message = error instanceof Error ? error.message : 'Unknown error'
    return (
      <div className="flex flex-col items-center justify-center py-24 text-center">
        <AlertCircle className="mb-4 h-10 w-10 text-rose-400" aria-hidden="true" />
        <h2 className="mb-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
          Failed to Load Thread
        </h2>
        <p className="mb-6 max-w-md text-sm text-slate-500 dark:text-slate-400">
          {message}
        </p>
        <div className="flex gap-3">
          <Button variant="outline" onClick={() => { void navigate('/') }}>
            <ArrowLeft className="mr-2 h-4 w-4" aria-hidden="true" />
            Dashboard
          </Button>
          <Button onClick={() => { void refetch() }}>
            <RefreshCw className="mr-2 h-4 w-4" aria-hidden="true" />
            Retry
          </Button>
        </div>
      </div>
    )
  }

  return <ReviewPane thread={thread} />
}
