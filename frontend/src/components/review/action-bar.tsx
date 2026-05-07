import { useState } from 'react'
import { CheckCircle, AlertTriangle, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { useApproveThread, useEscalateThread } from '@/hooks/use-mutation'
import type { Thread } from '@/lib/types'
import { cn } from '@/lib/utils'

interface ActionBarProps {
  thread: Thread
  draftedResponse: string
  onSuccess: () => void
}

export function ActionBar({ thread, draftedResponse, onSuccess }: ActionBarProps) {
  const [showApproveDialog, setShowApproveDialog] = useState(false)
  const [showEscalateDialog, setShowEscalateDialog] = useState(false)
  const [escalateReason, setEscalateReason] = useState('')

  const approveMutation = useApproveThread(thread.id)
  const escalateMutation = useEscalateThread(thread.id)

  const canApprove =
    thread.status === 'PENDING_REVIEW' &&
    !thread.operator_required &&
    draftedResponse.trim().length > 0

  const canEscalate =
    thread.status === 'PENDING_REVIEW' || thread.status === 'FAILED'

  const isActionable = canApprove || canEscalate
  const isTerminal = ['SENT_AUTO', 'ESCALATED', 'APPROVED'].includes(thread.status)

  const handleApprove = () => {
    approveMutation.mutate(
      { drafted_response: draftedResponse },
      {
        onSuccess: () => {
          setShowApproveDialog(false)
          onSuccess()
        },
      },
    )
  }

  const handleEscalate = () => {
    escalateMutation.mutate(
      { reason: escalateReason || undefined },
      {
        onSuccess: () => {
          setShowEscalateDialog(false)
          setEscalateReason('')
          onSuccess()
        },
      },
    )
  }

  if (isTerminal) {
    return (
      <div
        className={cn(
          'flex items-center gap-2 rounded-lg px-4 py-3 text-sm font-medium',
          thread.status === 'SENT_AUTO' && 'bg-emerald-50 text-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300',
          thread.status === 'APPROVED' && 'bg-blue-50 text-blue-800 dark:bg-blue-900/20 dark:text-blue-300',
          thread.status === 'ESCALATED' && 'bg-rose-50 text-rose-800 dark:bg-rose-900/20 dark:text-rose-300',
        )}
        role="status"
      >
        <CheckCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
        {thread.status === 'SENT_AUTO' && 'Response was sent automatically.'}
        {thread.status === 'APPROVED' && 'Response approved and queued for sending.'}
        {thread.status === 'ESCALATED' && 'Thread escalated for manual handling.'}
      </div>
    )
  }

  if (!isActionable) {
    return (
      <div
        className="flex items-center gap-2 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-500 dark:bg-slate-800/50 dark:text-slate-400"
        role="note"
      >
        <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" aria-hidden="true" />
        {thread.operator_required
          ? 'This thread is flagged for operator handling and cannot be auto-approved.'
          : 'Add a draft response to enable approval.'}
      </div>
    )
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        {canApprove && (
          <Button
            variant="success"
            onClick={() => { setShowApproveDialog(true) }}
            disabled={approveMutation.isPending || escalateMutation.isPending}
            className="flex-1 sm:flex-none"
            aria-label="Approve and send response"
          >
            <CheckCircle className="mr-2 h-4 w-4" aria-hidden="true" />
            Approve &amp; Send
          </Button>
        )}

        {canEscalate && (
          <Button
            variant="destructive"
            onClick={() => { setShowEscalateDialog(true) }}
            disabled={approveMutation.isPending || escalateMutation.isPending}
            className="flex-1 sm:flex-none"
            aria-label="Escalate thread for manual review"
          >
            <AlertTriangle className="mr-2 h-4 w-4" aria-hidden="true" />
            Escalate
          </Button>
        )}
      </div>

      {/* Approve confirmation dialog */}
      <Dialog open={showApproveDialog} onOpenChange={setShowApproveDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Confirm Approval</DialogTitle>
            <DialogDescription>
              This will approve and queue the drafted response for sending to the customer
              via Mirakl. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-md bg-slate-50 p-3 dark:bg-slate-800">
            <p className="text-xs text-slate-500 mb-1">Response preview:</p>
            <p className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap line-clamp-6">
              {draftedResponse}
            </p>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => { setShowApproveDialog(false) }}
              disabled={approveMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="success"
              onClick={handleApprove}
              disabled={approveMutation.isPending}
            >
              {approveMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  Approving...
                </>
              ) : (
                <>
                  <CheckCircle className="mr-2 h-4 w-4" aria-hidden="true" />
                  Confirm Approval
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Escalate confirmation dialog */}
      <Dialog open={showEscalateDialog} onOpenChange={setShowEscalateDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Escalate Thread</DialogTitle>
            <DialogDescription>
              This thread will be flagged for manual handling. Optionally provide
              a reason to assist the escalation team.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="escalate-reason">Reason (optional)</Label>
            <Textarea
              id="escalate-reason"
              placeholder="E.g. Customer claims product is defective, requires inspection..."
              value={escalateReason}
              onChange={(e) => { setEscalateReason(e.target.value) }}
              rows={4}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => { setShowEscalateDialog(false) }}
              disabled={escalateMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleEscalate}
              disabled={escalateMutation.isPending}
            >
              {escalateMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  Escalating...
                </>
              ) : (
                <>
                  <AlertTriangle className="mr-2 h-4 w-4" aria-hidden="true" />
                  Confirm Escalation
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
