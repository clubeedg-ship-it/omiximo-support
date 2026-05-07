import { useQuery } from '@tanstack/react-query'
import { fetchThread, fetchAuditLogs } from '@/lib/api'

export function useThread(id: number | null) {
  return useQuery({
    queryKey: ['thread', id],
    queryFn: () => fetchThread(id!),
    enabled: id !== null,
    staleTime: 30 * 1000,
  })
}

export function useAuditLogs(threadId: number | null) {
  return useQuery({
    queryKey: ['audit', threadId],
    queryFn: () => fetchAuditLogs(threadId!),
    enabled: threadId !== null,
    staleTime: 15 * 1000,
  })
}
