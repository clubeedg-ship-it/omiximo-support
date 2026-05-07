import { useQuery } from '@tanstack/react-query'
import { fetchReportSummary, fetchReportTimeline } from '@/lib/api'
import type { ReportParams } from '@/lib/types'

export function useReportSummary(params: ReportParams = {}) {
  return useQuery({
    queryKey: ['report-summary', params],
    queryFn: () => fetchReportSummary(params),
    staleTime: 2 * 60 * 1000,
    placeholderData: (prev) => prev,
  })
}

export function useReportTimeline(params: ReportParams = {}) {
  return useQuery({
    queryKey: ['report-timeline', params],
    queryFn: () => fetchReportTimeline(params),
    staleTime: 2 * 60 * 1000,
    placeholderData: (prev) => prev,
  })
}
