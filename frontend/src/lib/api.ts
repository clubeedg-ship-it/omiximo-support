import type {
  Thread,
  ThreadsResponse,
  MarketplaceAccount,
  Template,
  ThreadFilters,
  ApprovePayload,
  EscalatePayload,
  AlertsResponse,
  ReportSummary,
  ReportTimeline,
  ReportParams,
  ClassificationFlag,
  ClassifierCategoriesResponse,
  ClassificationFlagsParams,
  ClassificationFlagsResponse,
  FlagMisclassificationRequest,
  ResolveFlagRequest,
  TemplateOverride,
  CreateTemplateOverrideRequest,
} from './types'
import { getApiToken } from './auth'

const BASE_URL = (import.meta.env['VITE_API_URL'] as string | undefined) ?? 'http://localhost:8000'

async function request<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${BASE_URL}${path}`
  const headers = new Headers(options?.headers)
  if (options?.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const token = await getApiToken()
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const text = await response.text().catch(() => response.statusText)
    throw new Error(`API error ${response.status}: ${text}`)
  }

  // 204 No Content — return undefined cast to T
  if (response.status === 204) {
    return undefined as unknown as T
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

export async function fetchThread(id: string): Promise<Thread> {
  return request<Thread>(`/api/v1/threads/${id}`)
}

export async function approveThread(
  id: string,
  payload: ApprovePayload,
): Promise<Thread> {
  return request<Thread>(`/api/v1/threads/${id}/approve`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function escalateThread(
  id: string,
  payload: EscalatePayload,
): Promise<Thread> {
  return request<Thread>(`/api/v1/threads/${id}/escalate`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export async function fetchMarketplaces(): Promise<MarketplaceAccount[]> {
  return request<MarketplaceAccount[]>('/api/v1/marketplace-accounts')
}

export async function fetchTemplates(
  marketplaceAccountId?: string,
): Promise<Template[]> {
  const qs = marketplaceAccountId
    ? buildQueryString({ marketplace_account_id: marketplaceAccountId })
    : ''
  return request<Template[]>(`/api/v1/templates${qs}`)
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
  return request<ClassificationFlag>(`/api/v1/threads/${threadId}/flag-misclassification`, {
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
  return request<ClassificationFlagsResponse>(`/api/v1/classification/flags${qs}`)
}

export async function fetchClassificationCategories(): Promise<ClassifierCategoriesResponse> {
  return request<ClassifierCategoriesResponse>('/api/v1/classification/categories')
}

export async function resolveFlag(
  flagId: string,
  data: ResolveFlagRequest,
): Promise<ClassificationFlag> {
  return request<ClassificationFlag>(`/api/v1/classification/flags/${flagId}/resolve`, {
    method: 'PUT',
    body: JSON.stringify(data),
  })
}

export async function fetchTemplateOverrides(
  marketplaceAccountId: string,
): Promise<TemplateOverride[]> {
  return request<TemplateOverride[]>(`/api/v1/templates/overrides/${marketplaceAccountId}`)
}

export async function createTemplateOverride(
  data: CreateTemplateOverrideRequest,
): Promise<TemplateOverride> {
  return request<TemplateOverride>('/api/v1/templates/override', {
    method: 'POST',
    body: JSON.stringify(data),
  })
}

export async function deleteTemplateOverride(id: string): Promise<void> {
  return request<void>(`/api/v1/templates/overrides/${id}`, {
    method: 'DELETE',
  })
}
