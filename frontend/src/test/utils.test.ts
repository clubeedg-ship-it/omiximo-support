import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  cn,
  truncate,
  getLanguageLabel,
  getRiskLevelLabel,
  getStatusLabel,
  calculateSlaStatus,
  formatRelativeTime,
} from '@/lib/utils'

describe('cn()', () => {
  it('merges class names correctly', () => {
    expect(cn('foo', 'bar')).toBe('foo bar')
  })

  it('deduplicates conflicting tailwind classes', () => {
    expect(cn('bg-red-500', 'bg-blue-500')).toBe('bg-blue-500')
  })

  it('handles falsy values', () => {
    expect(cn('foo', false, null, undefined, 'bar')).toBe('foo bar')
  })
})

describe('truncate()', () => {
  it('returns short strings unchanged', () => {
    expect(truncate('hello', 80)).toBe('hello')
  })

  it('truncates long strings with ellipsis', () => {
    const long = 'a'.repeat(100)
    const result = truncate(long, 80)
    expect(result.endsWith('…')).toBe(true)
    expect(result.length).toBeLessThanOrEqual(81)
  })
})

describe('getLanguageLabel()', () => {
  it('returns Dutch for nl', () => expect(getLanguageLabel('nl')).toBe('Dutch'))
  it('returns English for en', () => expect(getLanguageLabel('en')).toBe('English'))
  it('returns French for fr', () => expect(getLanguageLabel('fr')).toBe('French'))
  it('returns German for de', () => expect(getLanguageLabel('de')).toBe('German'))
  it('uppercases unknown codes', () => expect(getLanguageLabel('xx')).toBe('XX'))
})

describe('getRiskLevelLabel()', () => {
  it('maps GREEN', () => expect(getRiskLevelLabel('GREEN')).toBe('Green'))
  it('maps ORANGE', () => expect(getRiskLevelLabel('ORANGE')).toBe('Orange'))
  it('maps RED', () => expect(getRiskLevelLabel('RED')).toBe('Red'))
})

describe('getStatusLabel()', () => {
  it('maps PENDING_REVIEW', () => expect(getStatusLabel('PENDING_REVIEW')).toBe('Pending Review'))
  it('maps SENT_AUTO', () => expect(getStatusLabel('SENT_AUTO')).toBe('Sent (Auto)'))
  it('maps ESCALATED', () => expect(getStatusLabel('ESCALATED')).toBe('Escalated'))
})

describe('calculateSlaStatus()', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('reports normal urgency when well within SLA', () => {
    const now = new Date('2024-01-01T12:00:00Z')
    vi.setSystemTime(now)
    // Created 1 hour ago, 24h SLA = 23h remaining
    const createdAt = new Date(now.getTime() - 1 * 60 * 60 * 1000).toISOString()
    const result = calculateSlaStatus(createdAt, null, 24)
    expect(result.urgency).toBe('normal')
    expect(result.isOverdue).toBe(false)
  })

  it('reports warning urgency within 6 hours', () => {
    const now = new Date('2024-01-01T12:00:00Z')
    vi.setSystemTime(now)
    // Created 19 hours ago, 24h SLA = 5h remaining
    const createdAt = new Date(now.getTime() - 19 * 60 * 60 * 1000).toISOString()
    const result = calculateSlaStatus(createdAt, null, 24)
    expect(result.urgency).toBe('warning')
  })

  it('reports critical urgency within 2 hours', () => {
    const now = new Date('2024-01-01T12:00:00Z')
    vi.setSystemTime(now)
    // Created 23 hours ago, 24h SLA = 1h remaining
    const createdAt = new Date(now.getTime() - 23 * 60 * 60 * 1000).toISOString()
    const result = calculateSlaStatus(createdAt, null, 24)
    expect(result.urgency).toBe('critical')
  })

  it('reports overdue when past deadline', () => {
    const now = new Date('2024-01-01T12:00:00Z')
    vi.setSystemTime(now)
    // Created 25 hours ago, 24h SLA = 1h overdue
    const createdAt = new Date(now.getTime() - 25 * 60 * 60 * 1000).toISOString()
    const result = calculateSlaStatus(createdAt, null, 24)
    expect(result.isOverdue).toBe(true)
    expect(result.urgency).toBe('overdue')
    expect(result.label).toContain('overdue')
  })

  it('respects explicit deadline over slaHours', () => {
    const now = new Date('2024-01-01T12:00:00Z')
    vi.setSystemTime(now)
    const createdAt = new Date(now.getTime() - 1 * 60 * 60 * 1000).toISOString()
    const pastDeadline = new Date(now.getTime() - 30 * 60 * 1000).toISOString()
    const result = calculateSlaStatus(createdAt, pastDeadline, 24)
    expect(result.isOverdue).toBe(true)
  })
})

describe('formatRelativeTime()', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('shows "just now" for very recent times', () => {
    const now = new Date()
    vi.setSystemTime(now)
    expect(formatRelativeTime(now.toISOString())).toBe('just now')
  })

  it('shows minutes for times within an hour', () => {
    const now = new Date()
    vi.setSystemTime(now)
    const past = new Date(now.getTime() - 30 * 60 * 1000)
    expect(formatRelativeTime(past.toISOString())).toBe('30m ago')
  })

  it('shows hours for times within a day', () => {
    const now = new Date()
    vi.setSystemTime(now)
    const past = new Date(now.getTime() - 5 * 60 * 60 * 1000)
    expect(formatRelativeTime(past.toISOString())).toBe('5h ago')
  })
})
