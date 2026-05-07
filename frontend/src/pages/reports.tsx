import { useState, useMemo } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useReportSummary, useReportTimeline } from '@/hooks/use-reports'
import { useMarketplaces } from '@/hooks/use-threads'
import { cn } from '@/lib/utils'
import type { ReportParams, TimelineEntry } from '@/lib/types'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pct(value: number): string {
  return `${Math.round(value * 100)}%`
}

function formatHours(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`
  return `${hours.toFixed(1)}h`
}

function barWidth(value: number, max: number): string {
  if (max === 0) return '0%'
  return `${Math.round((value / max) * 100)}%`
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

interface SummaryCardProps {
  label: string
  value: string
  sub?: string
  highlight?: 'green' | 'amber' | 'rose' | 'default'
}

function SummaryCard({ label, value, sub, highlight = 'default' }: SummaryCardProps) {
  const valueColor: Record<typeof highlight, string> = {
    green: 'text-emerald-700 dark:text-emerald-400',
    amber: 'text-amber-700 dark:text-amber-400',
    rose: 'text-rose-700 dark:text-rose-400',
    default: 'text-slate-900 dark:text-slate-100',
  }

  return (
    <Card className="flex-1 min-w-[140px]">
      <CardContent className="p-4">
        <p className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">{label}</p>
        <p className={cn('text-2xl font-bold tabular-nums', valueColor[highlight])}>{value}</p>
        {sub && (
          <p className="mt-0.5 text-xs text-slate-400 dark:text-slate-500">{sub}</p>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Horizontal bar chart row
// ---------------------------------------------------------------------------

interface BarRowProps {
  label: string
  value: number
  max: number
  colorClass: string
}

function BarRow({ label, value, max, colorClass }: BarRowProps) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-28 shrink-0 truncate text-xs text-slate-600 dark:text-slate-400" title={label}>
        {label}
      </span>
      <div
        className="flex-1 rounded-full bg-slate-100 dark:bg-slate-800 h-4 overflow-hidden"
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-label={`${label}: ${value}`}
      >
        <div
          className={cn('h-full rounded-full transition-all duration-300', colorClass)}
          style={{ width: barWidth(value, max) }}
        />
      </div>
      <span className="w-8 shrink-0 text-right text-xs tabular-nums text-slate-700 dark:text-slate-300">
        {value}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Stacked risk-level bar
// ---------------------------------------------------------------------------

interface StackedBarProps {
  green: number
  orange: number
  red: number
}

function StackedRiskBar({ green, orange, red }: StackedBarProps) {
  const total = green + orange + red
  if (total === 0) {
    return (
      <div className="h-8 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
        <span className="text-xs text-slate-400">No data</span>
      </div>
    )
  }

  const gPct = (green / total) * 100
  const oPct = (orange / total) * 100
  const rPct = (red / total) * 100

  return (
    <div className="space-y-2">
      <div
        className="flex h-8 overflow-hidden rounded-lg"
        role="img"
        aria-label={`Risk breakdown: ${green} green, ${orange} orange, ${red} red`}
      >
        {green > 0 && (
          <div
            className="bg-emerald-500 dark:bg-emerald-600 flex items-center justify-center"
            style={{ width: `${gPct}%` }}
            title={`Green: ${green}`}
          >
            <span className="text-white text-xs font-medium px-1 truncate">{green}</span>
          </div>
        )}
        {orange > 0 && (
          <div
            className="bg-amber-400 dark:bg-amber-500 flex items-center justify-center"
            style={{ width: `${oPct}%` }}
            title={`Orange: ${orange}`}
          >
            <span className="text-white text-xs font-medium px-1 truncate">{orange}</span>
          </div>
        )}
        {red > 0 && (
          <div
            className="bg-rose-500 dark:bg-rose-600 flex items-center justify-center"
            style={{ width: `${rPct}%` }}
            title={`Red: ${red}`}
          >
            <span className="text-white text-xs font-medium px-1 truncate">{red}</span>
          </div>
        )}
      </div>
      <div className="flex gap-4 text-xs">
        <span className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500" aria-hidden="true" />
          Green ({green})
        </span>
        <span className="flex items-center gap-1.5 text-amber-700 dark:text-amber-400">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-amber-400" aria-hidden="true" />
          Orange ({orange})
        </span>
        <span className="flex items-center gap-1.5 text-rose-700 dark:text-rose-400">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-rose-500" aria-hidden="true" />
          Red ({red})
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Donut chart (CSS only)
// ---------------------------------------------------------------------------

interface DonutSlice {
  label: string
  value: number
  colorClass: string
  hex: string
}

interface DonutChartProps {
  slices: DonutSlice[]
  total: number
}

function DonutChart({ slices, total }: DonutChartProps) {
  if (total === 0) {
    return (
      <div className="flex items-center justify-center h-32">
        <span className="text-xs text-slate-400">No data</span>
      </div>
    )
  }

  // Build conic-gradient segments
  let cumulative = 0
  const segments = slices
    .filter((s) => s.value > 0)
    .map((s) => {
      const startDeg = cumulative
      const deg = (s.value / total) * 360
      cumulative += deg
      return { ...s, startDeg, endDeg: cumulative }
    })

  const gradient = segments
    .map((s) => `${s.hex} ${s.startDeg}deg ${s.endDeg}deg`)
    .join(', ')

  return (
    <div className="flex flex-col sm:flex-row items-center gap-6">
      <div
        className="shrink-0 relative"
        role="img"
        aria-label="Marketplace distribution chart"
      >
        <div
          className="h-28 w-28 rounded-full"
          style={{ background: `conic-gradient(${gradient})` }}
        />
        {/* Donut hole */}
        <div className="absolute inset-0 m-auto h-14 w-14 rounded-full bg-white dark:bg-slate-900" />
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-sm font-bold text-slate-700 dark:text-slate-300">{total}</span>
        </div>
      </div>
      <ul className="flex flex-col gap-1.5 text-xs" aria-label="Marketplace legend">
        {segments.map((s) => (
          <li key={s.label} className="flex items-center gap-2">
            <span
              className={cn('inline-block h-2.5 w-2.5 rounded-sm shrink-0', s.colorClass)}
              aria-hidden="true"
            />
            <span className="text-slate-600 dark:text-slate-400 truncate max-w-[120px]" title={s.label}>
              {s.label}
            </span>
            <span className="ml-auto tabular-nums font-medium text-slate-700 dark:text-slate-300">
              {s.value}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Timeline sparkline
// ---------------------------------------------------------------------------

const TIMELINE_COLORS = {
  new_threads: { label: 'New', bg: 'bg-sky-400 dark:bg-sky-500' },
  resolved: { label: 'Resolved', bg: 'bg-emerald-400 dark:bg-emerald-500' },
  auto_sent: { label: 'Auto-sent', bg: 'bg-violet-400 dark:bg-violet-500' },
  escalated: { label: 'Escalated', bg: 'bg-rose-400 dark:bg-rose-500' },
} as const

type TimelineKey = keyof typeof TIMELINE_COLORS

interface TimelineChartProps {
  entries: TimelineEntry[]
}

function TimelineChart({ entries }: TimelineChartProps) {
  const maxValue = useMemo(() => {
    return Math.max(
      1,
      ...entries.flatMap((e) =>
        (Object.keys(TIMELINE_COLORS) as TimelineKey[]).map((k) => e[k]),
      ),
    )
  }, [entries])

  if (entries.length === 0) {
    return (
      <div className="flex items-center justify-center h-24">
        <span className="text-xs text-slate-400">No timeline data</span>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {(Object.keys(TIMELINE_COLORS) as TimelineKey[]).map((key) => {
        const meta = TIMELINE_COLORS[key]
        return (
          <div key={key} className="space-y-1">
            <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{meta.label}</p>
            <div
              className="flex items-end gap-0.5 h-8"
              role="img"
              aria-label={`${meta.label} over time`}
            >
              {entries.map((entry) => {
                const value = entry[key]
                const heightPct = (value / maxValue) * 100
                return (
                  <div
                    key={entry.date}
                    className="flex-1 flex flex-col justify-end"
                    title={`${entry.date}: ${value}`}
                  >
                    <div
                      className={cn('w-full rounded-sm', meta.bg, value === 0 && 'opacity-20')}
                      style={{ height: value === 0 ? '2px' : `${heightPct}%` }}
                    />
                  </div>
                )
              })}
            </div>
            <div className="flex justify-between text-[10px] text-slate-400 dark:text-slate-500">
              <span>{entries[0]?.date}</span>
              <span>{entries[entries.length - 1]?.date}</span>
            </div>
          </div>
        )
      })}

      {/* Legend */}
      <div className="flex flex-wrap gap-4 pt-1 border-t border-slate-100 dark:border-slate-800">
        {(Object.keys(TIMELINE_COLORS) as TimelineKey[]).map((key) => {
          const meta = TIMELINE_COLORS[key]
          return (
            <span key={key} className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400">
              <span className={cn('inline-block h-2.5 w-2.5 rounded-sm', meta.bg)} aria-hidden="true" />
              {meta.label}
            </span>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Donut palette
// ---------------------------------------------------------------------------

const MARKETPLACE_PALETTE = [
  { colorClass: 'bg-violet-500', hex: '#8b5cf6' },
  { colorClass: 'bg-sky-500', hex: '#0ea5e9' },
  { colorClass: 'bg-amber-500', hex: '#f59e0b' },
  { colorClass: 'bg-emerald-500', hex: '#10b981' },
  { colorClass: 'bg-rose-500', hex: '#f43f5e' },
  { colorClass: 'bg-slate-400', hex: '#94a3b8' },
]

// ---------------------------------------------------------------------------
// Day range options
// ---------------------------------------------------------------------------

const DAY_OPTIONS = [
  { label: 'Last 7 days', value: 7 },
  { label: 'Last 14 days', value: 14 },
  { label: 'Last 30 days', value: 30 },
]

// ---------------------------------------------------------------------------
// Main reports page
// ---------------------------------------------------------------------------

export function ReportsPage() {
  const [days, setDays] = useState<number>(7)
  const [marketplaceId, setMarketplaceId] = useState<number | ''>('')

  const { data: marketplaces = [] } = useMarketplaces()

  const params: ReportParams = {
    days,
    ...(marketplaceId !== '' ? { marketplace_account_id: marketplaceId } : {}),
  }

  const { data: summary, isLoading: summaryLoading } = useReportSummary(params)
  const { data: timeline, isLoading: timelineLoading } = useReportTimeline(params)

  const categoryMax = useMemo(() => {
    if (!summary) return 1
    const vals = Object.values(summary.by_category)
    return Math.max(1, ...vals)
  }, [summary])

  const donutSlices: DonutSlice[] = useMemo(() => {
    if (!summary) return []
    return Object.entries(summary.by_marketplace).map(([label, value], i) => ({
      label,
      value,
      ...MARKETPLACE_PALETTE[i % MARKETPLACE_PALETTE.length],
    }))
  }, [summary])

  const donutTotal = useMemo(
    () => donutSlices.reduce((acc, s) => acc + s.value, 0),
    [donutSlices],
  )

  const displayVal = (v: number | undefined, formatter: (n: number) => string) =>
    summaryLoading || v === undefined ? '—' : formatter(v)

  const slaHighlight =
    summary && summary.sla_compliance_rate >= 0.9
      ? 'green'
      : summary && summary.sla_compliance_rate < 0.7
        ? 'rose'
        : 'amber'

  const autoHighlight =
    summary && summary.auto_reply_rate >= 0.5 ? 'green' : 'default'

  return (
    <div className="space-y-6">
      {/* Page heading + filters */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-slate-100">Reports</h1>
          <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">
            Performance overview and trend analysis
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {marketplaces.length > 0 && (
            <Select
              value={marketplaceId === '' ? 'ALL' : String(marketplaceId)}
              onValueChange={(v) => { setMarketplaceId(v === 'ALL' ? '' : Number(v)) }}
            >
              <SelectTrigger className="h-8 w-[160px] text-xs" aria-label="Filter by marketplace">
                <SelectValue placeholder="All marketplaces" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">All marketplaces</SelectItem>
                {marketplaces.map((mp) => (
                  <SelectItem key={mp.id} value={String(mp.id)}>
                    {mp.marketplace}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}

          <Select
            value={String(days)}
            onValueChange={(v) => { setDays(Number(v)) }}
          >
            <SelectTrigger className="h-8 w-[140px] text-xs" aria-label="Select date range">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DAY_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={String(opt.value)}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Summary stat cards */}
      <section aria-label="Summary statistics">
        <div className="flex flex-wrap gap-3">
          <SummaryCard
            label="Total Threads"
            value={displayVal(summary?.total_threads, String)}
          />
          <SummaryCard
            label="Avg Response Time"
            value={displayVal(summary?.avg_response_time_hours, formatHours)}
            sub="from receipt to send"
          />
          <SummaryCard
            label="Auto-Reply Rate"
            value={displayVal(summary?.auto_reply_rate, pct)}
            sub="auto-sent / total"
            highlight={autoHighlight}
          />
          <SummaryCard
            label="SLA Compliance"
            value={displayVal(summary?.sla_compliance_rate, pct)}
            sub="threads answered in time"
            highlight={slaHighlight as 'green' | 'amber' | 'rose'}
          />
        </div>
      </section>

      {/* Charts grid */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {/* Risk level stacked bar */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              Threads by Risk Level
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {summaryLoading || !summary ? (
              <div className="h-16 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
            ) : (
              <StackedRiskBar
                green={summary.by_risk_level.green}
                orange={summary.by_risk_level.orange}
                red={summary.by_risk_level.red}
              />
            )}
          </CardContent>
        </Card>

        {/* Marketplace donut */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              By Marketplace
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {summaryLoading || !summary ? (
              <div className="h-32 animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
            ) : (
              <DonutChart slices={donutSlices} total={donutTotal} />
            )}
          </CardContent>
        </Card>

        {/* Threads by category */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              Threads by Category
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {summaryLoading || !summary ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-4 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
                ))}
              </div>
            ) : Object.keys(summary.by_category).length === 0 ? (
              <p className="text-xs text-slate-400 py-4 text-center">No data</p>
            ) : (
              <div className="space-y-2">
                {Object.entries(summary.by_category)
                  .sort(([, a], [, b]) => b - a)
                  .map(([category, count]) => (
                    <BarRow
                      key={category}
                      label={category}
                      value={count}
                      max={categoryMax}
                      colorClass="bg-sky-400 dark:bg-sky-500"
                    />
                  ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Timeline */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              Daily Activity
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {timelineLoading || !timeline ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-8 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
                ))}
              </div>
            ) : (
              <TimelineChart entries={timeline.entries} />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
