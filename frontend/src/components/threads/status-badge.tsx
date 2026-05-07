import { Badge } from '@/components/ui/badge'
import type { ThreadStatus } from '@/lib/types'
import { getStatusLabel } from '@/lib/utils'

interface StatusBadgeProps {
  status: ThreadStatus
  className?: string
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const variantMap: Record<ThreadStatus, 'green' | 'orange' | 'red' | 'blue' | 'slate' | 'secondary'> = {
    PENDING_REVIEW: 'orange',
    APPROVED: 'blue',
    SENT_AUTO: 'green',
    ESCALATED: 'red',
    FAILED: 'red',
  }

  return (
    <Badge variant={variantMap[status]} className={className}>
      {getStatusLabel(status)}
    </Badge>
  )
}
