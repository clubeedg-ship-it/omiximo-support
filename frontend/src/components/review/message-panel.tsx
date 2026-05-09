import { MessageSquare, Globe, Tag, Hash } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { RiskBadge } from '@/components/threads/risk-badge'
import { StatusBadge } from '@/components/threads/status-badge'
import type { Thread } from '@/lib/types'
import { formatDate, getLanguageLabel } from '@/lib/utils'

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
          >
            {thread.customer_message}
          </blockquote>
        </div>
      </CardContent>
    </Card>
  )
}
