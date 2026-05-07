import { useQuery } from '@tanstack/react-query'
import { fetchThreads, fetchMarketplaces } from '@/lib/api'
import type { ThreadFilters } from '@/lib/types'

export function useThreads(filters: ThreadFilters = {}, page = 1, pageSize = 50) {
  return useQuery({
    queryKey: ['threads', filters, page, pageSize],
    queryFn: () => fetchThreads(filters, page, pageSize),
    refetchInterval: 60 * 1000,
    placeholderData: (prev) => prev,
  })
}

export function useMarketplaces() {
  return useQuery({
    queryKey: ['marketplaces'],
    queryFn: fetchMarketplaces,
    staleTime: 5 * 60 * 1000,
  })
}
