import { useQuery } from '@tanstack/react-query'
import { fetchThread } from '@/lib/api'

export function useThread(id: string | null) {
  return useQuery({
    queryKey: ['thread', id],
    queryFn: () => fetchThread(id!),
    enabled: id !== null,
    staleTime: 30 * 1000,
  })
}
