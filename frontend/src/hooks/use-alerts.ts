import { useQuery } from '@tanstack/react-query'
import { fetchAlerts } from '@/lib/api'

export function useAlerts() {
  return useQuery({
    queryKey: ['alerts'],
    queryFn: fetchAlerts,
    refetchInterval: 60 * 1000,
    staleTime: 30 * 1000,
  })
}
