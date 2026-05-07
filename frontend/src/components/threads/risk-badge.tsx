import { Badge } from '@/components/ui/badge'
import type { RiskLevel } from '@/lib/types'
import { getRiskLevelLabel } from '@/lib/utils'

interface RiskBadgeProps {
  risk: RiskLevel | null
  className?: string
}

export function RiskBadge({ risk, className }: RiskBadgeProps) {
  if (!risk) {
    return (
      <Badge variant="secondary" className={className}>
        Unknown
      </Badge>
    )
  }

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
