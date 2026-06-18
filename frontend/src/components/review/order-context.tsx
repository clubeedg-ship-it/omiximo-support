import { Package, FileText, Truck, Clock, Tag, Globe, Store } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { RiskBadge } from '@/components/threads/risk-badge'
import { StatusBadge } from '@/components/threads/status-badge'
import { ReplyStateBadge } from '@/components/threads/reply-state-badge'
import { SlaIndicator } from '@/components/dashboard/sla-indicator'
import { getCategoryLabel, getLanguageLabel } from '@/lib/utils'
import type { Thread } from '@/lib/types'

interface OrderContextProps {
  thread: Thread
}

function ContextRow({ icon, label, value, badge }: {
  icon: React.ReactNode
  label: string
  value?: string | null
  badge?: React.ReactNode
}) {
  return (
    <div className="flex items-start justify-between gap-3 py-2.5">
      <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400 shrink-0">
        <span aria-hidden="true">{icon}</span>
        <span className="text-sm">{label}</span>
      </div>
      <div className="text-right">
        {badge ?? (
          <span className={`text-sm font-medium ${value ? 'text-slate-800 dark:text-slate-200' : 'text-slate-400 dark:text-slate-500'}`}>
            {value ?? 'Not available'}
          </span>
        )}
      </div>
    </div>
  )
}

function trackingStatusBadge(status: string | null) {
  if (!status) return null
  const lc = status.toLowerCase()
  if (lc.includes('delivered')) return <Badge variant="green">{status}</Badge>
  if (lc.includes('transit') || lc.includes('shipped')) return <Badge variant="blue">{status}</Badge>
  if (lc.includes('delay') || lc.includes('pending')) return <Badge variant="orange">{status}</Badge>
  if (lc.includes('fail') || lc.includes('return')) return <Badge variant="red">{status}</Badge>
  return <Badge variant="secondary">{status}</Badge>
}

export function OrderContext({ thread }: OrderContextProps) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Package className="h-4 w-4 text-slate-500" aria-hidden="true" />
          Info
        </CardTitle>
      </CardHeader>
      <CardContent className="divide-y divide-slate-100 dark:divide-slate-800">
        <ContextRow
          icon={<Package className="h-4 w-4" />}
          label="Order ID"
          value={thread.mirakl_order_id}
        />
        <ContextRow
          icon={<Store className="h-4 w-4" />}
          label="Marketplace"
          value={thread.marketplace_name ?? `Account #${thread.marketplace_account_id}`}
        />
        <ContextRow
          icon={<Tag className="h-4 w-4" />}
          label="Reply"
          badge={<ReplyStateBadge state={thread.reply_state} />}
        />
        <ContextRow
          icon={<Tag className="h-4 w-4" />}
          label="Status"
          badge={<StatusBadge status={thread.status} />}
        />
        <ContextRow
          icon={<Tag className="h-4 w-4" />}
          label="Category"
          value={thread.category ? getCategoryLabel(thread.category) : null}
        />
        <ContextRow
          icon={<Tag className="h-4 w-4" />}
          label="Risk"
          badge={thread.risk_level ? <RiskBadge risk={thread.risk_level} /> : undefined}
          value={thread.risk_level ? undefined : 'Not classified'}
        />
        <ContextRow
          icon={<Globe className="h-4 w-4" />}
          label="Language"
          value={thread.customer_language ? getLanguageLabel(thread.customer_language) : null}
        />
        {thread.operator_required && (
          <ContextRow
            icon={<Store className="h-4 w-4" />}
            label="Operator"
            badge={<Badge variant="red">Operator Required</Badge>}
          />
        )}
        <ContextRow
          icon={<Truck className="h-4 w-4" />}
          label="Tracking Status"
          badge={
            thread.tracking_status
              ? trackingStatusBadge(thread.tracking_status)
              : undefined
          }
          value={thread.tracking_status ? undefined : 'Not available'}
        />
        <ContextRow
          icon={<FileText className="h-4 w-4" />}
          label="Invoice Status"
          badge={
            thread.invoice_status
              ? <Badge variant="secondary">{thread.invoice_status}</Badge>
              : undefined
          }
          value={thread.invoice_status ? undefined : 'Not available'}
        />
        <div className="flex items-start justify-between gap-3 py-2.5">
          <div className="flex items-center gap-2 text-slate-500 dark:text-slate-400 shrink-0">
            <Clock className="h-4 w-4" aria-hidden="true" />
            <span className="text-sm">SLA Deadline</span>
          </div>
          <SlaIndicator
            createdAt={thread.created_at}
            deadline={thread.response_deadline}
            slaHours={thread.marketplace_account?.sla_hours ?? 24}
          />
        </div>
      </CardContent>
    </Card>
  )
}
