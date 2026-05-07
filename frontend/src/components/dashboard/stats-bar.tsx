import { AlertTriangle, CheckCircle, Clock, XCircle, Inbox } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { Thread } from '@/lib/types'
import { calculateSlaStatus } from '@/lib/utils'

interface StatsBarProps {
  threads: Thread[]
  isLoading: boolean
}

interface StatCardProps {
  label: string
  value: number | string
  icon: React.ReactNode
  colorClass: string
  bgClass: string
}

function StatCard({ label, value, icon, colorClass, bgClass }: StatCardProps) {
  return (
    <Card className="flex-1 min-w-[130px]">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-2">
          <div>
            <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">{label}</p>
            <p className={cn('text-2xl font-bold tabular-nums', colorClass)}>{value}</p>
          </div>
          <div className={cn('rounded-lg p-2', bgClass)}>
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function StatsBar({ threads, isLoading }: StatsBarProps) {
  const stats = {
    total: threads.length,
    green: threads.filter((t) => t.risk_level === 'GREEN').length,
    orange: threads.filter((t) => t.risk_level === 'ORANGE').length,
    red: threads.filter((t) => t.risk_level === 'RED').length,
    overdue: threads.filter((t) => {
      if (t.status === 'SENT_AUTO' || t.status === 'APPROVED' || t.status === 'ESCALATED') return false
      const sla = calculateSlaStatus(
        t.created_at,
        t.response_deadline,
        t.marketplace_account?.sla_hours ?? 24,
      )
      return sla.isOverdue
    }).length,
    pending: threads.filter((t) => t.status === 'PENDING_REVIEW').length,
  }

  const displayValue = (n: number) => (isLoading ? '—' : n)

  return (
    <div
      className="flex flex-wrap gap-3"
      role="region"
      aria-label="Support queue statistics"
    >
      <StatCard
        label="Pending Review"
        value={displayValue(stats.pending)}
        icon={<Inbox className="h-4 w-4 text-slate-600 dark:text-slate-400" />}
        colorClass="text-slate-900 dark:text-slate-100"
        bgClass="bg-slate-100 dark:bg-slate-800"
      />
      <StatCard
        label="Green (Low Risk)"
        value={displayValue(stats.green)}
        icon={<CheckCircle className="h-4 w-4 text-emerald-600" />}
        colorClass="text-emerald-700 dark:text-emerald-400"
        bgClass="bg-emerald-50 dark:bg-emerald-900/20"
      />
      <StatCard
        label="Orange (Medium)"
        value={displayValue(stats.orange)}
        icon={<AlertTriangle className="h-4 w-4 text-amber-600" />}
        colorClass="text-amber-700 dark:text-amber-400"
        bgClass="bg-amber-50 dark:bg-amber-900/20"
      />
      <StatCard
        label="Red (High Risk)"
        value={displayValue(stats.red)}
        icon={<XCircle className="h-4 w-4 text-rose-600" />}
        colorClass="text-rose-700 dark:text-rose-400"
        bgClass="bg-rose-50 dark:bg-rose-900/20"
      />
      <StatCard
        label="SLA Overdue"
        value={displayValue(stats.overdue)}
        icon={<Clock className="h-4 w-4 text-rose-600" />}
        colorClass={stats.overdue > 0 ? 'text-rose-700 dark:text-rose-400' : 'text-slate-900 dark:text-slate-100'}
        bgClass={stats.overdue > 0 ? 'bg-rose-50 dark:bg-rose-900/20' : 'bg-slate-100 dark:bg-slate-800'}
      />
    </div>
  )
}
