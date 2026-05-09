import { useState, useEffect } from 'react'
import DOMPurify from 'dompurify'
import { MessageSquare, Globe, Tag, Hash, Sparkles, ChevronRight, ChevronDown, Loader2, AlertCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { RiskBadge } from '@/components/threads/risk-badge'
import { StatusBadge } from '@/components/threads/status-badge'
import type { Thread } from '@/lib/types'
import { fetchThreadInsight, type InsightResponse } from '@/lib/api'
import { formatDate, getLanguageLabel } from '@/lib/utils'

function sanitizeHtml(raw: string): string {
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: ['br', 'p', 'b', 'strong', 'i', 'em', 'a', 'ul', 'ol', 'li'],
    ALLOWED_ATTR: ['href'],
  })
}

interface MessagePanelProps {
  thread: Thread
}

function MetaItem({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-start gap-2">
      <div className="mt-0.5 text-slate-400 shrink-0" aria-hidden="true">{icon}</div>
      <div>
        <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
        <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{value}</p>
      </div>
    </div>
  )
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

export function MessagePanel({ thread }: MessagePanelProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquare className="h-4 w-4 text-slate-500" aria-hidden="true" />
          Customer Message
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <MetaItem
            icon={<Hash className="h-3.5 w-3.5" />}
            label="Order ID"
            value={thread.mirakl_order_id}
          />
          <MetaItem
            icon={<Tag className="h-3.5 w-3.5" />}
            label="Category"
            value={thread.category ?? '—'}
          />
          <MetaItem
            icon={<Globe className="h-3.5 w-3.5" />}
            label="Language"
            value={thread.customer_language ? getLanguageLabel(thread.customer_language) : '—'}
          />
          <MetaItem
            icon={<Globe className="h-3.5 w-3.5" />}
            label="Marketplace"
            value={thread.marketplace_name ?? `Account #${thread.marketplace_account_id}`}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <RiskBadge risk={thread.risk_level} />
          <StatusBadge status={thread.status} />
          {thread.operator_required && (
            <span className="inline-flex items-center rounded-full border border-rose-300 bg-rose-50 px-2.5 py-0.5 text-xs font-semibold text-rose-700 dark:border-rose-700 dark:bg-rose-900/20 dark:text-rose-300">
              Operator Required
            </span>
          )}
        </div>

        <Separator />

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

        <AiInsightCard threadId={String(thread.id)} />
      </CardContent>
    </Card>
  )
}
