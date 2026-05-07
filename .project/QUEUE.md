# QUEUE

## Phase 1 — Central inbox + draft generation (no auto-send)

| id | lane | title | status | deps | next_action |
|---|---|---|---|---|---|
| P1.1 | infra | Scaffold from fastapi template + docker compose | todo | none | clone template, strip example crud, docker compose up with postgres |
| P1.2 | backend | DB schema: marketplace_accounts, support_threads, audit_log, response_templates | todo | P1.1 | Alembic migrations for all four tables per CLAUDE.md spec |
| P1.3 | backend | Mirakl thread collector | todo | P1.2 | poll each active marketplace_account, fetch new/updated threads, store in support_threads |
| P1.4 | backend | Order data enrichment | todo | P1.3 | for each thread, fetch order status, tracking, invoice from Mirakl order API |
| P1.5 | backend | Classification engine (LLM) | todo | P1.4 | send message + order context to LLM, extract category + risk_level + language |
| P1.6 | backend | Template engine + draft generation | todo | P1.5 | match category + language to response_templates, fill order data slots, store drafted_response |
| P1.7 | backend | Safety rules module | todo | P1.6 | safety_rules.py — hard blocks per D3 before any status transition |
| P1.8 | backend | API: GET /threads, GET /threads/{id}, PUT /approve, PUT /escalate | todo | P1.7 | CRUD + actions, approve triggers Mirakl reply API + audit_log write |
| P1.9 | frontend | Triage dashboard (DataTable) | todo | P1.8 | shadcn DataTable: time elapsed, marketplace, order_id, risk badge, review button |
| P1.10 | frontend | Review pane | todo | P1.9 | split view: message + order context (left), editable draft + approve/escalate (right) |
| P1.11 | backend | Seed initial templates (nl/en/fr/de) | todo | P1.2 | tracking, invoice, return, complaint, defect templates per client doc |

## Phase 2 — Safe auto-replies for Green cases

| id | lane | title | status | deps | next_action |
|---|---|---|---|---|---|
| P2.1 | backend | Auto-send validation rules | todo | P1.7 | green + valid tracking + template match + safety pass → SENT_AUTO eligible |
| P2.2 | backend | Auto-send execution path | todo | P2.1 | background task: send eligible, audit_log, update status |
| P2.3 | backend | Webhook ingestion endpoint | todo | P1.3 | POST /api/v1/mirakl/webhook — real-time push instead of polling |
| P2.4 | infra | Cloudflare Tunnel setup | todo | P2.3 | tunnel → api:8000, register webhook URL in Mirakl |
| P2.5 | backend | Carrier tracking connector | todo | P1.4 | ConnectorBase for PostNL/MyParcel/FedEx |
| P2.6 | backend | Invoice connector | todo | P1.4 | ConnectorBase for EasyBill |

## Phase 3 — Incident prevention

| id | lane | title | status | deps | next_action |
|---|---|---|---|---|---|
| P3.1 | backend | SLA deadline monitoring | todo | P2.2 | flag threads approaching sla_hours |
| P3.2 | backend | Missing tracking / invoice alerts | todo | P2.5 | warn on shipped-but-no-tracking, missing invoice |
| P3.3 | frontend | Alert banners on dashboard | todo | P3.1 | overdue + at-risk + missing-data warnings |

## Phase 4 — Reporting + advanced automation

| id | lane | title | status | deps | next_action |
|---|---|---|---|---|---|
| P4.1 | backend | Reporting endpoints | todo | P2.2 | avg response time, auto-reply %, incident risk per marketplace |
| P4.2 | frontend | Reporting dashboard | todo | P4.1 | charts: response time, auto-reply rate, risk distribution |
| P4.3 | backend | Marketplace-specific template rules | todo | P1.11 | per-marketplace overrides where policy differs |
| P4.4 | backend | Classification tuning from real data | todo | P2.2 | weekly review: flag misclassifications, adjust prompts |

Notes:
- Auto-send stays OFF through all of Phase 1. Draft-only mode.
- Phase 2 starts only after drafts prove reliable with real messages.
- P2.3/P2.4 (webhook) can run parallel with P2.1/P2.2 (auto-send).
- Carrier/invoice connectors (P2.5/P2.6) independent — build when API access is available.
