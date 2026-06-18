import { useState, useEffect } from 'react'
import DOMPurify from 'dompurify'
import { MessageSquare, Sparkles, ChevronRight, ChevronDown, Loader2, AlertCircle, EyeOff } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { Thread, ThreadMessage, MessageAuthorType } from '@/lib/types'
import { fetchThreadInsight, type InsightResponse } from '@/lib/api'
import { formatDate } from '@/lib/utils'

function sanitizeHtml(raw: string): string {
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: ['br', 'p', 'b', 'strong', 'i', 'em', 'a', 'ul', 'ol', 'li'],
    ALLOWED_ATTR: ['href'],
  })
}

interface MessagePanelProps {
  thread: Thread
}

type InsightState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'done'; data: InsightResponse }

function AiInsightCard({ threadId }: { threadId: string }) {
  const [state, setState] = useState<InsightState>({ status: 'loading' })
  const [translationOpen, setTranslationOpen] = useState(false)

  useEffect(() => {
    let cancelled = false

    fetchThreadInsight(threadId)
      .then((data) => {
        if (!cancelled) setState({ status: 'done', data })
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' })
      })

    return () => { cancelled = true }
  }, [threadId])

  const insight = state.status === 'done' ? state.data : null

  const hasTranslation = Boolean(insight?.translated_message?.trim())

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3 dark:bg-blue-900/20 dark:border-blue-800">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-blue-500 dark:text-blue-400 shrink-0" aria-hidden="true" />
        <span className="text-sm font-semibold text-blue-800 dark:text-blue-300">AI Summary</span>
      </div>

      {state.status === 'loading' && (
        <div className="flex items-center gap-2 text-sm text-blue-400 dark:text-blue-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          <span>Generating insight...</span>
        </div>
      )}

      {state.status === 'error' && (
        <div className="flex items-center gap-2 text-sm text-slate-400 dark:text-slate-500">
          <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Insight unavailable</span>
        </div>
      )}

      {state.status === 'done' && insight?.summary && (
        <p className="text-sm leading-relaxed text-blue-900 dark:text-blue-200">
          {insight.summary}
        </p>
      )}

      {state.status === 'done' && !insight?.summary && (
        <p className="text-sm text-slate-400 dark:text-slate-500">
          No summary available for this message.
        </p>
      )}

      {hasTranslation && (
        <div>
          <button
            type="button"
            onClick={() => setTranslationOpen((prev) => !prev)}
            className="flex items-center gap-1.5 text-xs font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 transition-colors"
            aria-expanded={translationOpen}
            aria-controls="ai-translation-content"
          >
            {translationOpen ? (
              <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {translationOpen ? 'Hide translation' : 'Show translation'}
          </button>

          {translationOpen && (
            <div id="ai-translation-content">
              <div className="mt-2 border-t border-blue-200 dark:border-blue-700 pt-2">
                <div
                  className="text-sm leading-relaxed text-blue-700 dark:text-blue-300 bg-blue-100/60 dark:bg-blue-900/40 rounded px-3 py-2"
                  dangerouslySetInnerHTML={{ __html: sanitizeHtml(insight?.translated_message ?? '') }}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const AUTHOR_TYPE_LABELS: Record<MessageAuthorType, string> = {
  CUSTOMER: 'Customer',
  SHOP_USER: 'Omiximo',
  OPERATOR: 'Operator',
  SYSTEM: 'System',
}

const AVATAR_STYLES: Record<MessageAuthorType, string> = {
  CUSTOMER: 'bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
  SHOP_USER: 'bg-emerald-200 text-emerald-800 dark:bg-emerald-800 dark:text-emerald-100',
  OPERATOR: 'bg-amber-200 text-amber-900 dark:bg-amber-800 dark:text-amber-100',
  SYSTEM: 'bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-300',
}

function senderLabel(message: ThreadMessage): string {
  return message.author_name?.trim() || AUTHOR_TYPE_LABELS[message.author_type]
}

function recipientLabel(message: ThreadMessage): string {
  return message.direction === 'OUTBOUND' ? 'Customer' : 'Omiximo'
}

function avatarInitial(message: ThreadMessage): string {
  const source = message.author_name?.trim() || AUTHOR_TYPE_LABELS[message.author_type]
  return source.charAt(0).toUpperCase()
}

function formatDayLabel(dateString: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(new Date(dateString))
}

function MessageBubble({ message }: { message: ThreadMessage }) {
  const isOutbound = message.direction === 'OUTBOUND'
  const isOperator = message.author_type === 'OPERATOR'

  const bubbleStyle = isOutbound
    ? 'border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-100'
    : isOperator
      ? 'border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-100'
      : 'border-slate-200 bg-slate-50 text-slate-800 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-200'

  return (
    <div className={`flex flex-col gap-1.5 ${isOutbound ? 'items-end' : 'items-start'}`}>
      <div className={`flex items-center gap-2 ${isOutbound ? 'flex-row-reverse' : 'flex-row'}`}>
        <span
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${AVATAR_STYLES[message.author_type]}`}
          aria-hidden="true"
        >
          {avatarInitial(message)}
        </span>
        <div className={`flex flex-wrap items-center gap-x-1.5 gap-y-0.5 ${isOutbound ? 'justify-end' : ''}`}>
          <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">
            {senderLabel(message)}
          </span>
          <span className="text-xs text-slate-400 dark:text-slate-500">→ {recipientLabel(message)}</span>
          {isOperator && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
              <EyeOff className="h-3 w-3" aria-hidden="true" />
              Not visible to customer
            </span>
          )}
        </div>
      </div>
      <div
        className={`max-w-[88%] rounded-lg border px-4 py-3 text-sm leading-relaxed ${bubbleStyle}`}
        role="article"
        aria-label={`${senderLabel(message)} message`}
        dangerouslySetInnerHTML={{ __html: sanitizeHtml(message.body) }}
      />
      <span className="text-xs text-slate-400 dark:text-slate-500 tabular-nums">
        {formatDate(message.created_at)}
      </span>
    </div>
  )
}

function DateSeparator({ label }: { label: string }) {
  return (
    <div className="flex items-center justify-center" role="separator" aria-label={label}>
      <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400">
        {label}
      </span>
    </div>
  )
}

function ConversationTimeline({ messages }: { messages: ThreadMessage[] }) {
  const sorted = [...messages].sort((a, b) => a.sequence_number - b.sequence_number)

  let lastDay = ''
  return (
    <div className="space-y-4" role="log" aria-label="Conversation timeline" aria-live="off">
      {sorted.map((message) => {
        const day = formatDayLabel(message.created_at)
        const showSeparator = day !== lastDay
        lastDay = day
        return (
          <div key={message.id} className="space-y-4">
            {showSeparator && <DateSeparator label={day} />}
            <MessageBubble message={message} />
          </div>
        )
      })}
    </div>
  )
}

function participantsLine(messages: ThreadMessage[]): string {
  const seen = new Set<string>()
  const names: string[] = []
  for (const m of messages) {
    const name = senderLabel(m)
    if (!seen.has(name)) {
      seen.add(name)
      names.push(name)
    }
  }
  return names.join(', ')
}

export function MessagePanel({ thread }: MessagePanelProps) {
  const messages = Array.isArray(thread.messages) ? thread.messages : []
  const hasMessages = messages.length > 0

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquare className="h-4 w-4 text-slate-500" aria-hidden="true" />
          Conversation
        </CardTitle>
        {hasMessages && (
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Participants: {participantsLine(messages)}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {hasMessages ? (
          <ConversationTimeline messages={messages} />
        ) : (
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-400 dark:text-slate-500">
              Received {formatDate(thread.created_at)}
            </p>
            <blockquote
              className="rounded-md border-l-4 border-slate-200 bg-slate-50 p-4 text-sm leading-relaxed text-slate-800 dark:border-slate-700 dark:bg-slate-800/50 dark:text-slate-200"
              aria-label="Customer message content"
              dangerouslySetInnerHTML={{ __html: sanitizeHtml(thread.customer_message) }}
            />
          </div>
        )}

        <AiInsightCard threadId={String(thread.id)} />
      </CardContent>
    </Card>
  )
}
