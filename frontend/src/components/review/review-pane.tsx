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
  return thread.status === 'PENDING_REVIEW'
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

      {/* Mirakl-style layout: main = conversation + reply composer, right = Info */}
      <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr] lg:items-start">
        {/* Main: conversation timeline, then the reply composer beneath it */}
        <div className="space-y-4" role="region" aria-label="Conversation and reply">
          <MessagePanel thread={thread} />
          <DraftEditor
            threadId={String(thread.id)}
            value={draftedResponse}
            onChange={setDraftedResponse}
            isEditable={isEditable}
            threadStatus={thread.status}
            targetLanguage={thread.customer_language ?? 'en'}
          />
          <ActionBar
            thread={thread}
            draftedResponse={draftedResponse}
            onSuccess={handleSuccess}
          />
        </div>

        {/* Right: order/customer info sidebar */}
        <div className="space-y-4 lg:sticky lg:top-4" role="region" aria-label="Order information">
          <OrderContext thread={thread} />
        </div>
      </div>
    </div>
  )
}
