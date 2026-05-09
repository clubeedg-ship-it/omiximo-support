import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  fetchClassificationCategories,
  fetchClassificationFlags,
  flagMisclassification,
  resolveFlag,
} from '@/lib/api'
import type {
  ClassifierCategoriesResponse,
  ClassificationFlagsParams,
  FlagMisclassificationRequest,
  ResolveFlagRequest,
} from '@/lib/types'

export function useClassifierCategories() {
  return useQuery<ClassifierCategoriesResponse>({
    queryKey: ['classification-categories'],
    queryFn: fetchClassificationCategories,
    staleTime: 5 * 60 * 1000,
  })
}

export function useClassificationFlags(params: ClassificationFlagsParams = {}) {
  return useQuery({
    queryKey: ['classification-flags', params],
    queryFn: () => fetchClassificationFlags(params),
    staleTime: 30 * 1000,
    placeholderData: (prev) => prev,
  })
}

export function useFlagMisclassification(threadId: string) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: FlagMisclassificationRequest) =>
      flagMisclassification(threadId, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['classification-flags'] })
      toast.success('Classification flag submitted successfully.')
    },
    onError: (error: Error) => {
      toast.error(`Failed to submit flag: ${error.message}`)
    },
  })
}

export function useResolveFlag() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ flagId, data }: { flagId: string; data: ResolveFlagRequest }) =>
      resolveFlag(flagId, data),
    onSuccess: (_, { data }) => {
      void queryClient.invalidateQueries({ queryKey: ['classification-flags'] })
      const label = data.resolution === 'accepted' ? 'accepted' : 'rejected'
      toast.success(`Flag ${label}.`)
    },
    onError: (error: Error) => {
      toast.error(`Failed to resolve flag: ${error.message}`)
    },
  })
}
