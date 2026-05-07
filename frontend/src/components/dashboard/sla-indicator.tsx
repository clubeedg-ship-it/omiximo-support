import { Clock } from 'lucide-react'
import { cn, calculateSlaStatus } from '@/lib/utils'

interface SlaIndicatorProps {
  createdAt: string
  deadline: string | null
  slaHours?: number
  className?: string
}

export function SlaIndicator({ createdAt, deadline, slaHours = 24, className }: SlaIndicatorProps) {
  const sla = calculateSlaStatus(createdAt, deadline, slaHours)

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <Clock
        className={cn(
          'h-4 w-4 shrink-0',
          sla.urgency === 'overdue' && 'text-rose-500',
          sla.urgency === 'critical' && 'text-rose-400',
          sla.urgency === 'warning' && 'text-amber-500',
          sla.urgency === 'normal' && 'text-emerald-500',
        )}
        aria-hidden="true"
      />
      <div className="flex flex-col gap-0.5 min-w-0">
        <span
          className={cn(
            'text-xs font-semibold leading-none',
            sla.urgency === 'overdue' && 'text-rose-600 dark:text-rose-400',
            sla.urgency === 'critical' && 'text-rose-500 dark:text-rose-400',
            sla.urgency === 'warning' && 'text-amber-600 dark:text-amber-400',
            sla.urgency === 'normal' && 'text-slate-600 dark:text-slate-400',
          )}
        >
          {sla.label}
        </span>
        <div
          className="h-1.5 w-20 rounded-full bg-slate-100 dark:bg-slate-700 overflow-hidden"
          role="progressbar"
          aria-valuenow={sla.percentage}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`SLA: ${sla.label}`}
        >
          <div
            className={cn(
              'h-full rounded-full transition-all duration-300',
              sla.urgency === 'overdue' && 'bg-rose-500 w-full',
              sla.urgency === 'critical' && 'bg-rose-400',
              sla.urgency === 'warning' && 'bg-amber-400',
              sla.urgency === 'normal' && 'bg-emerald-400',
            )}
            style={sla.urgency !== 'overdue' ? { width: `${sla.percentage}%` } : undefined}
          />
        </div>
      </div>
    </div>
  )
}
