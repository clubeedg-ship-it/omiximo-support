export type RiskLevel = 'GREEN' | 'ORANGE' | 'RED'

export type ThreadStatus =
  | 'PENDING_REVIEW'
  | 'APPROVED'
  | 'SENT_AUTO'
  | 'ESCALATED'
  | 'FAILED'

export type Language = 'nl' | 'en' | 'fr' | 'de'

export interface MarketplaceAccount {
  id: string
  marketplace: string
  shop_id: string
  base_url: string
  sla_hours: number
  template_set: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface Thread {
  id: string
  mirakl_thread_id: string
  mirakl_order_id: string
  marketplace_account_id: string
  marketplace_name?: string | null
  marketplace_account?: MarketplaceAccount
  customer_language: Language | null
  category: string | null
  risk_level: RiskLevel | null
  status: ThreadStatus
  operator_required: boolean
  customer_message: string
  drafted_response: string | null
  message_summary?: string | null
  translated_message?: string | null
  tracking_status: string | null
  invoice_status: string | null
  response_deadline: string
  created_at: string
  updated_at: string
}

export interface Template {
  id: string
  marketplace_account_id: string | null
  category: string
  language: Language
  template_body: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface AuditLog {
  id: string
  thread_id: string | null
  action: string
  actor: string
  detail_json: Record<string, unknown> | null
  created_at: string
}

export interface ThreadFilters {
  risk_level?: RiskLevel | ''
  status?: ThreadStatus | ''
  marketplace_account_id?: string | ''
  search?: string
}

export interface ThreadsResponse {
  items: Thread[]
  total: number
  page: number
  page_size: number
}

export interface ApprovePayload {
  drafted_response_override?: string | null
}

export interface EscalatePayload {
  reason: string
}

export interface SLAAlert {
  thread_id: string
  deadline: string
  hours_remaining: number
  marketplace: string
}

export interface DataAlert {
  thread_id: string
  alert_type: string
  message: string
  created_at: string
}

export interface AlertsResponse {
  sla_approaching: SLAAlert[]
  sla_overdue: SLAAlert[]
  missing_data: DataAlert[]
  total_count: number
}

export interface ReportSummary {
  total_threads: number
  by_risk_level: Record<string, number>
  by_status: Record<string, number>
  avg_response_time_hours: number
  auto_reply_rate: number
  sla_compliance_rate: number
  by_category: Record<string, number>
  by_marketplace: Record<string, number>
}

export interface TimelineEntry {
  date: string
  new_threads: number
  resolved: number
  auto_sent: number
  escalated: number
}

export interface ReportTimeline {
  granularity: string
  points: TimelineEntry[]
}

export interface ReportParams {
  marketplace_account_id?: string | ''
  days?: number
}

export interface ClassificationFlag {
  id: string
  thread_id: string
  original_category: string | null
  original_risk_level: string | null
  original_language: string | null
  correct_category: string
  correct_risk_level: string
  correct_language: string
  reason: string
  actor: string
  resolution: 'accepted' | 'rejected' | null
  resolved_by: string | null
  resolved_at: string | null
  created_at: string
}

export interface FlagMisclassificationRequest {
  correct_category: string
  correct_risk_level: RiskLevel
  correct_language: Language
  reason: string
}

export interface ResolveFlagRequest {
  resolution: 'accepted' | 'rejected'
}

export interface TemplateOverride {
  id: string
  marketplace_account_id: string
  category: string
  language: string
  template_body: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ClassificationFlagsParams {
  reviewed?: boolean
  page?: number
  page_size?: number
}

export interface ClassificationFlagsResponse {
  items: ClassificationFlag[]
  total: number
  page: number
  page_size: number
}

export interface ClassifierCategoriesResponse {
  categories: string[]
}

export interface CreateTemplateOverrideRequest {
  marketplace_account_id: string
  category: string
  language: Language
  template_body: string
}
