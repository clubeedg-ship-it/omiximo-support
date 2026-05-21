import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import type { RiskLevel, ThreadStatus } from './types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDate(dateString: string): string {
  const date = new Date(dateString)
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function formatRelativeTime(dateString: string): string {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)
  const diffWeeks = Math.floor(diffDays / 7)
  const diffMonths = Math.floor(diffDays / 30)
  const diffYears = Math.floor(diffDays / 365)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  if (diffDays < 30) return diffWeeks === 1 ? '~1 week ago' : `~${diffWeeks} weeks ago`
  if (diffDays < 365) return diffMonths === 1 ? '~1 month ago' : `~${diffMonths} months ago`
  return diffYears === 1 ? '~1 year ago' : `~${diffYears} years ago`
}

export interface SlaStatus {
  hoursRemaining: number
  minutesRemaining: number
  isOverdue: boolean
  urgency: 'normal' | 'warning' | 'critical' | 'overdue'
  label: string
  percentage: number
}

export function calculateSlaStatus(
  createdAt: string,
  deadlineString: string | null,
  slaHours = 24,
): SlaStatus {
  const now = new Date()
  let deadline: Date

  if (deadlineString) {
    deadline = new Date(deadlineString)
  } else {
    const created = new Date(createdAt)
    deadline = new Date(created.getTime() + slaHours * 60 * 60 * 1000)
  }

  const totalMs = deadline.getTime() - new Date(createdAt).getTime()
  const remainingMs = deadline.getTime() - now.getTime()
  const elapsedMs = now.getTime() - new Date(createdAt).getTime()

  const hoursRemaining = Math.floor(remainingMs / (1000 * 60 * 60))
  const minutesRemaining = Math.floor((remainingMs % (1000 * 60 * 60)) / (1000 * 60))

  const isOverdue = remainingMs < 0

  const percentage = Math.min(100, Math.max(0, (elapsedMs / totalMs) * 100))

  let urgency: SlaStatus['urgency']
  let label: string

  if (isOverdue) {
    urgency = 'overdue'
    const overdueMs = Math.abs(remainingMs)
    const overdueDays = Math.floor(overdueMs / (1000 * 60 * 60 * 24))
    const overdueWeeks = Math.floor(overdueDays / 7)
    const overdueMonths = Math.floor(overdueDays / 30)
    const overdueYears = Math.floor(overdueDays / 365)
    const overdueHrs = Math.abs(hoursRemaining)
    const overdueMins = Math.abs(minutesRemaining)

    if (overdueYears >= 1) label = overdueYears === 1 ? '~1 year overdue' : `~${overdueYears} years overdue`
    else if (overdueMonths >= 1) label = overdueMonths === 1 ? '~1 month overdue' : `~${overdueMonths} months overdue`
    else if (overdueWeeks >= 1) label = overdueWeeks === 1 ? '~1 week overdue' : `~${overdueWeeks} weeks overdue`
    else if (overdueDays >= 1) label = `${overdueDays}d overdue`
    else if (overdueHrs >= 1) label = `${overdueHrs}h overdue`
    else label = `${overdueMins}m overdue`
  } else if (hoursRemaining < 2) {
    urgency = 'critical'
    label = minutesRemaining > 0 ? `${hoursRemaining}h ${minutesRemaining}m left` : `${hoursRemaining}h left`
  } else if (hoursRemaining < 6) {
    urgency = 'warning'
    label = `${hoursRemaining}h left`
  } else {
    urgency = 'normal'
    label = `${hoursRemaining}h left`
  }

  return { hoursRemaining, minutesRemaining, isOverdue, urgency, label, percentage }
}

export function getRiskLevelLabel(risk: RiskLevel): string {
  const labels: Record<RiskLevel, string> = {
    GREEN: 'Green',
    ORANGE: 'Orange',
    RED: 'Red',
  }
  return labels[risk]
}

export function getStatusLabel(status: ThreadStatus): string {
  const labels: Record<ThreadStatus, string> = {
    PENDING_REVIEW: 'Pending Review',
    APPROVED: 'Approved',
    SENT_AUTO: 'Sent (Auto)',
    ESCALATED: 'Escalated',
    FAILED: 'Failed',
  }
  return labels[status]
}

export function getLanguageLabel(lang: string): string {
  const labels: Record<string, string> = {
    nl: 'Dutch',
    en: 'English',
    fr: 'French',
    de: 'German',
  }
  return labels[lang] ?? lang.toUpperCase()
}

export function truncate(text: string, maxLength = 80): string {
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength).trimEnd() + '…'
}

/**
 * Strip HTML tags and decode common entities to render a plain-text preview
 * of email-style content (Outlook, Gmail, Mirakl forwards, etc.).
 *
 * Removes <script>/<style> blocks entirely (including their content), then
 * strips all remaining tags, decodes a handful of common HTML entities, and
 * collapses whitespace.
 */
export function stripHtml(html: string): string {
  if (!html) return ''
  // Drop entire <script>, <style>, and <head> blocks (content included)
  const withoutBlocks = html.replace(
    /<(script|style|head)\b[^>]*>[\s\S]*?<\/\1>/gi,
    ' ',
  )
  // Strip remaining tags
  const withoutTags = withoutBlocks.replace(/<[^>]+>/g, ' ')
  // Decode common entities
  const decoded = withoutTags
    .replace(/&nbsp;/gi, ' ')
    .replace(/&#160;/g, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;/g, "'")
    .replace(/&#(\d+);/g, (_, code: string) => String.fromCharCode(parseInt(code, 10)))
  // Collapse whitespace
  return decoded.replace(/\s+/g, ' ').trim()
}
