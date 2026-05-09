import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { MessagePanel } from './message-panel'
import { OrderContext } from './order-context'
import { DraftEditor } from './draft-editor'
import { ActionBar } from './action-bar'
import type { Thread } from '@/lib/types'

interface ReviewPaneProps {
  thread: Thread
}

function canEditDraft(thread: Thread): boolean {
  return thread.status === 'PENDING_REVIEW' && !thread.operator_required
}

export function ReviewPane({ thread }: ReviewPaneProps) {
  const navigate = useNavigate()
  const [draftedResponse, setDraftedResponse] = useState(thread.drafted_response ?? '')

  const handleSuccess = useCallback(() => {
    void navigate('/')
  }, [navigate])

  const isEditable = canEditDraft(thread)

  return (
    <div className="space-y-4">
      {/* Back navigation */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => { void navigate(-1) }}
          aria-label="Go back to dashboard"
        >
          <ArrowLeft className="mr-1.5 h-4 w-4" aria-hidden="true" />
          Back
        </Button>
        <Separator orientation="vertical" className="h-5" />
        <div>
          <h1 className="text-base font-semibold text-slate-900 dark:text-slate-100">
            Review Thread
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Order {thread.mirakl_order_id}
            {thread.marketplace_name
              ? ` · ${thread.marketplace_name}`
              : ''}
          </p>
        </div>
      </div>

      {/* Split layout: left = context, right = draft + actions */}
      <div className="grid gap-4 lg:grid-cols-[1fr,1fr]">
        {/* Left: customer message + order context */}
        <div className="space-y-4" role="region" aria-label="Thread context">
          <MessagePanel thread={thread} />
          <OrderContext thread={thread} />
        </div>

        {/* Right: draft editor + action bar */}
        <div className="space-y-4" role="region" aria-label="Response draft and actions">
          <DraftEditor
            value={draftedResponse}
            onChange={setDraftedResponse}
            isEditable={isEditable}
            threadStatus={thread.status}
          />
          <ActionBar
            thread={thread}
            draftedResponse={draftedResponse}
            onSuccess={handleSuccess}
          />
        </div>
      </div>
    </div>
  )
}
