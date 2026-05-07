import { useMutation, useQueryClient } from '@tanstack/react-query'
import { approveThread, escalateThread } from '@/lib/api'
import { toast } from 'sonner'
import type { ApprovePayload, EscalatePayload } from '@/lib/types'

export function useApproveThread(threadId: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: ApprovePayload) => approveThread(threadId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['threads'] })
      void queryClient.invalidateQueries({ queryKey: ['thread', threadId] })
      toast.success('Response approved and queued for sending.')
    },
    onError: (error: Error) => {
      toast.error(`Approval failed: ${error.message}`)
    },
  })
}

export function useEscalateThread(threadId: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (payload: EscalatePayload) => escalateThread(threadId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['threads'] })
      void queryClient.invalidateQueries({ queryKey: ['thread', threadId] })
      toast.success('Thread escalated for manual review.')
    },
    onError: (error: Error) => {
      toast.error(`Escalation failed: ${error.message}`)
    },
  })
}
