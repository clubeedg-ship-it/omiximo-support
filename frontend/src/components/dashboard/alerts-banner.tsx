import { useState, useCallback, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
import { X, AlertTriangle, Clock, PackageSearch, ChevronDown } from 'lucide-react'
import { useAlerts } from '@/hooks/use-alerts'
import { cn } from '@/lib/utils'

type DismissedKey = 'sla_overdue' | 'sla_approaching' | 'missing_data'

interface BannerProps {
  variant: 'red' | 'amber' | 'blue'
  icon: React.ReactNode
  message: string
  links: Array<{ label: string; to: string }>
  onDismiss: () => void
}

function Banner({ variant, icon, message, links, onDismiss }: BannerProps) {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => { document.removeEventListener('mousedown', handleClickOutside) }
  }, [open])

  const variantClasses: Record<typeof variant, string> = {
    red: 'bg-rose-50 border-rose-200 text-rose-900 dark:bg-rose-950/40 dark:border-rose-800 dark:text-rose-200',
    amber: 'bg-amber-50 border-amber-200 text-amber-900 dark:bg-amber-950/40 dark:border-amber-800 dark:text-amber-200',
    blue: 'bg-sky-50 border-sky-200 text-sky-900 dark:bg-sky-950/40 dark:border-sky-800 dark:text-sky-200',
  }

  const iconClasses: Record<typeof variant, string> = {
    red: 'text-rose-500 dark:text-rose-400',
    amber: 'text-amber-500 dark:text-amber-400',
    blue: 'text-sky-500 dark:text-sky-400',
  }

  const linkClasses: Record<typeof variant, string> = {
    red: 'text-rose-700 hover:text-rose-900 hover:bg-rose-100 dark:text-rose-300 dark:hover:text-rose-100 dark:hover:bg-rose-900/40',
    amber: 'text-amber-700 hover:text-amber-900 hover:bg-amber-100 dark:text-amber-300 dark:hover:text-amber-100 dark:hover:bg-amber-900/40',
    blue: 'text-sky-700 hover:text-sky-900 hover:bg-sky-100 dark:text-sky-300 dark:hover:text-sky-100 dark:hover:bg-sky-900/40',
  }

  const toggleClasses: Record<typeof variant, string> = {
    red: 'text-rose-700 hover:bg-rose-100 dark:text-rose-300 dark:hover:bg-rose-900/40',
    amber: 'text-amber-700 hover:bg-amber-100 dark:text-amber-300 dark:hover:bg-amber-900/40',
    blue: 'text-sky-700 hover:bg-sky-100 dark:text-sky-300 dark:hover:bg-sky-900/40',
  }

  const popoverClasses: Record<typeof variant, string> = {
    red: 'bg-white border-rose-200 dark:bg-slate-900 dark:border-rose-800',
    amber: 'bg-white border-amber-200 dark:bg-slate-900 dark:border-amber-800',
    blue: 'bg-white border-sky-200 dark:bg-slate-900 dark:border-sky-800',
  }

  const dismissClasses: Record<typeof variant, string> = {
    red: 'text-rose-400 hover:text-rose-700 dark:text-rose-500 dark:hover:text-rose-300',
    amber: 'text-amber-400 hover:text-amber-700 dark:text-amber-500 dark:hover:text-amber-300',
    blue: 'text-sky-400 hover:text-sky-700 dark:text-sky-500 dark:hover:text-sky-300',
  }

  return (
    <div
      ref={containerRef}
      role="alert"
      className={cn(
        'relative flex items-center gap-3 rounded-lg border px-4 py-2 text-sm',
        variantClasses[variant],
      )}
    >
      <span className={cn('shrink-0', iconClasses[variant])} aria-hidden="true">
        {icon}
      </span>
      <p className="flex-1 min-w-0 font-medium truncate">{message}</p>
      {links.length > 0 && (
        <button
          type="button"
          onClick={() => { setOpen((v) => !v) }}
          className={cn(
            'shrink-0 inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium transition-colors',
            toggleClasses[variant],
          )}
          aria-expanded={open}
        >
          {open ? 'Hide' : 'See all'}
          <ChevronDown
            className={cn('h-3 w-3 transition-transform', open && 'rotate-180')}
            aria-hidden="true"
          />
        </button>
      )}
      <button
        type="button"
        onClick={onDismiss}
        className={cn('shrink-0 rounded p-0.5 transition-colors', dismissClasses[variant])}
        aria-label="Dismiss alert"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>

      {open && links.length > 0 && (
        <div
          className={cn(
            'absolute right-4 top-full z-20 mt-1 w-80 max-h-96 overflow-y-auto rounded-lg border shadow-lg',
            popoverClasses[variant],
          )}
        >
          <ul className="py-1 text-sm">
            {links.map((link) => (
              <li key={link.to}>
                <Link
                  to={link.to}
                  onClick={() => { setOpen(false) }}
                  className={cn(
                    'block px-3 py-1.5 transition-colors',
                    linkClasses[variant],
                  )}
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export function AlertsBanner() {
  const { data: alerts } = useAlerts()
  const [dismissed, setDismissed] = useState<Set<DismissedKey>>(new Set())

  const dismiss = useCallback((key: DismissedKey) => {
    setDismissed((prev) => {
      const next = new Set(prev)
      next.add(key)
      return next
    })
  }, [])

  if (!alerts) return null

  const hasOverdue = alerts.sla_overdue.length > 0 && !dismissed.has('sla_overdue')
  const hasApproaching = alerts.sla_approaching.length > 0 && !dismissed.has('sla_approaching')
  const hasMissingData = alerts.missing_data.length > 0 && !dismissed.has('missing_data')

  if (!hasOverdue && !hasApproaching && !hasMissingData) return null

  return (
    <div
      className="flex flex-col gap-2"
      role="region"
      aria-label="Alert notifications"
    >
      {hasOverdue && (
        <Banner
          variant="red"
          icon={<AlertTriangle className="h-4 w-4" />}
          message={`${alerts.sla_overdue.length} thread${alerts.sla_overdue.length !== 1 ? 's are' : ' is'} past SLA deadline`}
          links={alerts.sla_overdue.map((a) => ({
            label: `Thread ${a.thread_id} (${a.marketplace})`,
            to: `/review/${a.thread_id}`,
          }))}
          onDismiss={() => { dismiss('sla_overdue') }}
        />
      )}

      {hasApproaching && (
        <Banner
          variant="amber"
          icon={<Clock className="h-4 w-4" />}
          message={`${alerts.sla_approaching.length} thread${alerts.sla_approaching.length !== 1 ? 's are' : ' is'} approaching SLA deadline (< 1h remaining)`}
          links={alerts.sla_approaching.map((a) => ({
            label: `Thread ${a.thread_id} (${a.marketplace})`,
            to: `/review/${a.thread_id}`,
          }))}
          onDismiss={() => { dismiss('sla_approaching') }}
        />
      )}

      {hasMissingData && (
        <Banner
          variant="blue"
          icon={<PackageSearch className="h-4 w-4" />}
          message={`${alerts.missing_data.length} thread${alerts.missing_data.length !== 1 ? 's are' : ' is'} missing tracking/invoice data`}
          links={alerts.missing_data.map((a) => ({
            label: `Thread ${a.thread_id}`,
            to: `/review/${a.thread_id}`,
          }))}
          onDismiss={() => { dismiss('missing_data') }}
        />
      )}
    </div>
  )
}
