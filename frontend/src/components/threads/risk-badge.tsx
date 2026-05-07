import { Badge } from '@/components/ui/badge'
import type { RiskLevel } from '@/lib/types'
import { getRiskLevelLabel } from '@/lib/utils'

interface RiskBadgeProps {
  risk: RiskLevel
  className?: string
}

export function RiskBadge({ risk, className }: RiskBadgeProps) {
  const variantMap = {
    GREEN: 'green',
    ORANGE: 'orange',
    RED: 'red',
  } as const

  return (
    <Badge variant={variantMap[risk]} className={className}>
      {getRiskLevelLabel(risk)}
    </Badge>
  )
}
