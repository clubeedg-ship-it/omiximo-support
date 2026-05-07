import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBadge } from '@/components/threads/status-badge'
import type { ThreadStatus } from '@/lib/types'

const statuses: Array<{ status: ThreadStatus; label: string }> = [
  { status: 'PENDING_REVIEW', label: 'Pending Review' },
  { status: 'APPROVED', label: 'Approved' },
  { status: 'SENT_AUTO', label: 'Sent (Auto)' },
  { status: 'ESCALATED', label: 'Escalated' },
  { status: 'FAILED', label: 'Failed' },
]

describe('StatusBadge', () => {
  statuses.forEach(({ status, label }) => {
    it(`renders "${label}" for ${status}`, () => {
      render(<StatusBadge status={status} />)
      expect(screen.getByText(label)).toBeInTheDocument()
    })
  })
})
