import type {
  Thread,
  ThreadsResponse,
  MarketplaceAccount,
  Template,
  AuditLog,
  ThreadFilters,
  ApprovePayload,
  EscalatePayload,
  AlertsResponse,
  ReportSummary,
  ReportTimeline,
  ReportParams,
  ClassificationFlag,
  ClassificationFlagsParams,
  ClassificationFlagsResponse,
  FlagMisclassificationRequest,
  ResolveFlagRequest,
  TemplateOverride,
  CreateTemplateOverrideRequest,
} from './types'

const BASE_URL = (import.meta.env['VITE_API_URL'] as string | undefined) ?? 'http://localhost:8000'

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${BASE_URL}${path}`
  const response = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  })

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText)
    throw new Error(`API error ${response.status}: ${text}`)
  }

  return response.json() as Promise<T>
}

function buildQueryString(params: Record<string, string | number | boolean | undefined>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== '' && v !== null,
  )
  if (entries.length === 0) return ''
  return '?' + new URLSearchParams(
    entries.map(([k, v]) => [k, String(v)]),
  ).toString()
}

export async function fetchThreads(
  filters: ThreadFilters = {},
  page = 1,
  pageSize = 50,
): Promise<ThreadsResponse> {
  const qs = buildQueryString({
    ...(filters.risk_level ? { risk_level: filters.risk_level } : {}),
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.marketplace_account_id ? { marketplace_account_id: filters.marketplace_account_id } : {}),
    ...(filters.search ? { search: filters.search } : {}),
    page,
    page_size: pageSize,
  })
  return request<ThreadsResponse>(`/api/v1/threads${qs}`)
}

export async function fetchThread(id: number): Promise<Thread> {
  return request<Thread>(`/api/v1/threads/${id}`)
}

export async function approveThread(
  id: number,
  payload: ApprovePayload,
): Promise<Thread> {
  return request<Thread>(`/api/v1/threads/${id}/approve`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function escalateThread(
  id: number,
  payload: EscalatePayload = {},
): Promise<Thread> {
  return request<Thread>(`/api/v1/threads/${id}/escalate`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function fetchMarketplaces(): Promise<MarketplaceAccount[]> {
  return request<MarketplaceAccount[]>('/api/v1/marketplaces')
}

export async function fetchTemplates(
  marketplaceAccountId?: number,
): Promise<Template[]> {
  const qs = marketplaceAccountId
    ? buildQueryString({ marketplace_account_id: marketplaceAccountId })
    : ''
  return request<Template[]>(`/api/v1/templates${qs}`)
}

export async function fetchAuditLogs(threadId: number): Promise<AuditLog[]> {
  return request<AuditLog[]>(`/api/v1/threads/${threadId}/audit`)
}

export async function fetchAlerts(): Promise<AlertsResponse> {
  return request<AlertsResponse>('/api/v1/alerts')
}

export async function fetchReportSummary(params: ReportParams = {}): Promise<ReportSummary> {
  const qs = buildQueryString({
    ...(params.marketplace_account_id ? { marketplace_account_id: params.marketplace_account_id } : {}),
    ...(params.days ? { days: params.days } : {}),
  })
  return request<ReportSummary>(`/api/v1/reports/summary${qs}`)
}

export async function fetchReportTimeline(params: ReportParams = {}): Promise<ReportTimeline> {
  const qs = buildQueryString({
    ...(params.marketplace_account_id ? { marketplace_account_id: params.marketplace_account_id } : {}),
    ...(params.days ? { days: params.days } : {}),
  })
  return request<ReportTimeline>(`/api/v1/reports/timeline${qs}`)
}

export async function flagMisclassification(
  threadId: string,
  data: FlagMisclassificationRequest,
): Promise<ClassificationFlag> {
  return request<ClassificationFlag>(`/api/v1/threads/${threadId}/flag-classification`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function fetchClassificationFlags(
  params: ClassificationFlagsParams = {},
): Promise<ClassificationFlagsResponse> {
  const qs = buildQueryString({
    ...(params.reviewed !== undefined ? { reviewed: params.reviewed } : {}),
    ...(params.page !== undefined ? { page: params.page } : {}),
    ...(params.page_size !== undefined ? { page_size: params.page_size } : {}),
  })
  return request<ClassificationFlagsResponse>(`/api/v1/classification-flags${qs}`)
}

export async function resolveFlag(
  flagId: string,
  data: ResolveFlagRequest,
): Promise<ClassificationFlag> {
  return request<ClassificationFlag>(`/api/v1/classification-flags/${flagId}/resolve`, {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function fetchTemplateOverrides(
  marketplaceAccountId: string,
): Promise<TemplateOverride[]> {
  const qs = buildQueryString({ marketplace_account_id: marketplaceAccountId })
  return request<TemplateOverride[]>(`/api/v1/template-overrides${qs}`)
}

export async function createTemplateOverride(
  data: CreateTemplateOverrideRequest,
): Promise<TemplateOverride> {
  return request<TemplateOverride>('/api/v1/template-overrides', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function deleteTemplateOverride(id: string): Promise<void> {
  return request<void>(`/api/v1/template-overrides/${id}`, {
    method: 'DELETE',
  })
}
