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

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  return `${diffDays}d ago`
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
    const overdueHours = Math.abs(hoursRemaining)
    const overdueMins = Math.abs(minutesRemaining)
    label = overdueHours > 0 ? `${overdueHours}h overdue` : `${overdueMins}m overdue`
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
