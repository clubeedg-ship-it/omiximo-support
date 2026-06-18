import { Badge } from '@/components/ui/badge'
import type { ReplyState } from '@/lib/types'
import { getReplyStateLabel } from '@/lib/utils'

interface ReplyStateBadgeProps {
  state?: ReplyState | null
  className?: string
}

export function ReplyStateBadge({ state, className }: ReplyStateBadgeProps) {
  if (!state) {
    return <span className="text-xs text-slate-400 dark:text-slate-500">—</span>
  }

  const variantMap: Record<ReplyState, 'orange' | 'blue' | 'slate'> = {
    NEEDS_REPLY: 'orange',
    AWAITING_CUSTOMER: 'blue',
    RESOLVED: 'slate',
  }

  return (
    <Badge variant={variantMap[state]} className={className}>
      {getReplyStateLabel(state)}
    </Badge>
  )
}
