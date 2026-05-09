import { useMemo, useState } from 'react'
import { CheckCircle, AlertTriangle, Flag, Loader2 } from 'lucide-react'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useApproveThread, useEscalateThread } from '@/hooks/use-mutation'
import {
  useClassifierCategories,
  useFlagMisclassification,
} from '@/hooks/use-classification'
import type { Thread, RiskLevel, Language } from '@/lib/types'
import { cn } from '@/lib/utils'

const RISK_LEVELS: RiskLevel[] = ['GREEN', 'ORANGE', 'RED']
const LANGUAGES: Language[] = ['nl', 'en', 'fr', 'de']

interface ActionBarProps {
  thread: Thread
  draftedResponse: string
  onSuccess: () => void
}

export function ActionBar({ thread, draftedResponse, onSuccess }: ActionBarProps) {
  const [showApproveDialog, setShowApproveDialog] = useState(false)
  const [showEscalateDialog, setShowEscalateDialog] = useState(false)
  const [showFlagDialog, setShowFlagDialog] = useState(false)
  const [escalateReason, setEscalateReason] = useState('')

  // Flag form state
  const [flagCategory, setFlagCategory] = useState<string>(thread.category ?? 'general_inquiry')
  const [flagRiskLevel, setFlagRiskLevel] = useState<RiskLevel>(thread.risk_level ?? 'ORANGE')
  const [flagLanguage, setFlagLanguage] = useState<Language>(thread.customer_language ?? 'nl')
  const [flagReason, setFlagReason] = useState('')

  const approveMutation = useApproveThread(thread.id)
  const escalateMutation = useEscalateThread(thread.id)
  const flagMutation = useFlagMisclassification(String(thread.id))
  const { data: classifierCategories } = useClassifierCategories()

  const categoryOptions = useMemo(() => {
    const backendCategories = classifierCategories?.categories ?? []
    if (backendCategories.length === 0) {
      return [flagCategory]
    }
    if (backendCategories.includes(flagCategory)) {
      return backendCategories
    }
    return [flagCategory, ...backendCategories]
  }, [classifierCategories, flagCategory])

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
      { drafted_response_override: draftedResponse || null },
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
      { reason: escalateReason || 'Manual escalation' },
      {
        onSuccess: () => {
          setShowEscalateDialog(false)
          setEscalateReason('')
          onSuccess()
        },
      },
    )
  }

  const handleFlag = () => {
    if (!flagReason.trim()) return
    flagMutation.mutate(
      {
        correct_category: flagCategory,
        correct_risk_level: flagRiskLevel,
        correct_language: flagLanguage,
        reason: flagReason,
      },
      {
        onSuccess: () => {
          setShowFlagDialog(false)
          setFlagReason('')
        },
      },
    )
  }

  const flagButton = (
    <Button
      variant="outline"
      onClick={() => { setShowFlagDialog(true) }}
      disabled={approveMutation.isPending || escalateMutation.isPending}
      className="flex-1 sm:flex-none border-amber-300 text-amber-700 hover:bg-amber-50 hover:text-amber-800 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-900/20 dark:hover:text-amber-300"
      aria-label="Flag classification as incorrect"
    >
      <Flag className="mr-2 h-4 w-4" aria-hidden="true" />
      Flag Classification
    </Button>
  )

  if (isTerminal) {
    return (
      <>
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
        <div className="flex flex-wrap items-center gap-3 mt-2">
          {flagButton}
        </div>
        {flagDialog()}
      </>
    )
  }

  if (!isActionable) {
    return (
      <>
        <div
          className="flex items-center gap-2 rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-500 dark:bg-slate-800/50 dark:text-slate-400"
          role="note"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" aria-hidden="true" />
          {thread.operator_required
            ? 'This thread is flagged for operator handling and cannot be auto-approved.'
            : 'Add a draft response to enable approval.'}
        </div>
        <div className="flex flex-wrap items-center gap-3 mt-2">
          {flagButton}
        </div>
        {flagDialog()}
      </>
    )
  }

  function flagDialog() {
    return (
      <Dialog open={showFlagDialog} onOpenChange={setShowFlagDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Flag Classification</DialogTitle>
            <DialogDescription>
              Report an incorrect classification for this thread. Your correction
              will be reviewed and used to improve future accuracy.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 rounded-md bg-slate-50 p-3 text-xs dark:bg-slate-800">
              <div>
                <p className="text-slate-500 dark:text-slate-400 mb-0.5">Current category</p>
                <p className="font-medium text-slate-700 dark:text-slate-300">{thread.category ?? '—'}</p>
              </div>
              <div>
                <p className="text-slate-500 dark:text-slate-400 mb-0.5">Current risk level</p>
                <p className="font-medium text-slate-700 dark:text-slate-300">{thread.risk_level ?? '—'}</p>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="flag-category">Correct category</Label>
              <Select value={flagCategory} onValueChange={setFlagCategory}>
                <SelectTrigger id="flag-category" aria-label="Select correct category">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {categoryOptions.map((cat) => (
                    <SelectItem key={cat} value={cat}>
                      {cat}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="flag-risk">Correct risk level</Label>
              <Select
                value={flagRiskLevel}
                onValueChange={(v) => { setFlagRiskLevel(v as RiskLevel) }}
              >
                <SelectTrigger id="flag-risk" aria-label="Select correct risk level">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {RISK_LEVELS.map((level) => (
                    <SelectItem key={level} value={level}>
                      {level}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="flag-language">Correct language</Label>
              <Select
                value={flagLanguage}
                onValueChange={(v) => { setFlagLanguage(v as Language) }}
              >
                <SelectTrigger id="flag-language" aria-label="Select correct language">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LANGUAGES.map((lang) => (
                    <SelectItem key={lang} value={lang}>
                      {lang.toUpperCase()}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="flag-reason">
                Reason <span className="text-rose-500" aria-hidden="true">*</span>
              </Label>
              <Textarea
                id="flag-reason"
                placeholder="Explain why the classification is incorrect..."
                value={flagReason}
                onChange={(e) => { setFlagReason(e.target.value) }}
                rows={3}
                aria-required="true"
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => { setShowFlagDialog(false) }}
              disabled={flagMutation.isPending}
            >
              Cancel
            </Button>
            <Button
              onClick={handleFlag}
              disabled={flagMutation.isPending || !flagReason.trim()}
              className="bg-amber-500 hover:bg-amber-600 text-white dark:bg-amber-600 dark:hover:bg-amber-700"
            >
              {flagMutation.isPending ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                  Submitting...
                </>
              ) : (
                <>
                  <Flag className="mr-2 h-4 w-4" aria-hidden="true" />
                  Submit Flag
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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

        {flagButton}
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

      {flagDialog()}
    </>
  )
}
