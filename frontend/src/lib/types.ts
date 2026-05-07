export type RiskLevel = 'GREEN' | 'ORANGE' | 'RED'

export type ThreadStatus =
  | 'PENDING_REVIEW'
  | 'APPROVED'
  | 'SENT_AUTO'
  | 'ESCALATED'
  | 'FAILED'

export type Language = 'nl' | 'en' | 'fr' | 'de'

export interface MarketplaceAccount {
  id: number
  marketplace: string
  shop_id: string
  base_url: string
  sla_hours: number
  template_set: string
  is_active: boolean
}

export interface Thread {
  id: number
  mirakl_thread_id: string
  mirakl_order_id: string
  marketplace_account_id: number
  marketplace_account?: MarketplaceAccount
  customer_language: Language
  category: string
  risk_level: RiskLevel
  status: ThreadStatus
  operator_required: boolean
  customer_message: string
  drafted_response: string | null
  tracking_status: string | null
  invoice_status: string | null
  response_deadline: string | null
  created_at: string
  updated_at: string
}

export interface Template {
  id: number
  marketplace_account_id: number | null
  category: string
  language: Language
  template_body: string
  is_active: boolean
}

export interface AuditLog {
  id: number
  thread_id: number
  action: string
  actor: string
  detail_json: Record<string, unknown>
  created_at: string
}

export interface ThreadFilters {
  risk_level?: RiskLevel | ''
  status?: ThreadStatus | ''
  marketplace_account_id?: number | ''
  search?: string
}

export interface ThreadsResponse {
  items: Thread[]
  total: number
  page: number
  page_size: number
}

export interface ApprovePayload {
  drafted_response: string
}

export interface EscalatePayload {
  reason?: string
}

export interface SLAAlert {
  thread_id: string
  deadline: string
  hours_remaining: number
  marketplace: string
}

export interface DataAlert {
  thread_id: string
  alert_type: 'missing_tracking' | 'missing_invoice'
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
  by_risk_level: { green: number; orange: number; red: number }
  by_status: { pending: number; approved: number; sent_auto: number; escalated: number; failed: number }
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
  entries: TimelineEntry[]
}

export interface ReportParams {
  marketplace_account_id?: number | ''
  days?: number
}
