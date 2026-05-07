# QUEUE

## Phase 1 — Central inbox + draft generation (no auto-send)

| id | lane | title | status | deps | next_action |
|---|---|---|---|---|---|
| P1.1 | infra | Scaffold from fastapi template + docker compose | done | none | — |
| P1.2 | backend | DB schema: marketplace_accounts, support_threads, audit_log, response_templates | done | P1.1 | — |
| P1.3 | backend | Mirakl thread collector | done | P1.2 | — |
| P1.4 | backend | Order data enrichment | done | P1.3 | — |
| P1.5 | backend | Classification engine (LLM) | done | P1.4 | — |
| P1.6 | backend | Template engine + draft generation | done | P1.5 | — |
| P1.7 | backend | Safety rules module | done | P1.6 | — |
| P1.8 | backend | API: GET /threads, GET /threads/{id}, PUT /approve, PUT /escalate | done | P1.7 | — |
| P1.9 | frontend | Triage dashboard (DataTable) | done | P1.8 | — |
| P1.10 | frontend | Review pane | done | P1.9 | — |
| P1.11 | backend | Seed initial templates (nl/en/fr/de) | done | P1.2 | — |

## Phase 2 — Safe auto-replies for Green cases

| id | lane | title | status | deps | next_action |
|---|---|---|---|---|---|
| P2.1 | backend | Auto-send validation rules | done | P1.7 | — |
| P2.2 | backend | Auto-send execution path | done | P2.1 | — |
| P2.3 | backend | Webhook ingestion endpoint | done | P1.3 | — |
| P2.4 | infra | Cloudflare Tunnel setup | blocked | P2.3 | needs server + domain config |
| P2.5 | backend | Carrier tracking connector | blocked | P1.4 | needs API credentials (PostNL/MyParcel/FedEx) |
| P2.6 | backend | Invoice connector | blocked | P1.4 | needs EasyBill API credentials |

## Phase 3 — Incident prevention

| id | lane | title | status | deps | next_action |
|---|---|---|---|---|---|
| P3.1 | backend | SLA deadline monitoring | done | P2.2 | — |
| P3.2 | backend | Missing tracking / invoice alerts | done | P2.5 | — |
| P3.3 | frontend | Alert banners on dashboard | done | P3.1 | — |

## Phase 4 — Reporting + advanced automation

| id | lane | title | status | deps | next_action |
|---|---|---|---|---|---|
| P4.1 | backend | Reporting endpoints | done | P2.2 | — |
| P4.2 | frontend | Reporting dashboard | done | P4.1 | — |
| P4.3 | backend | Marketplace-specific template rules | todo | P1.11 | per-marketplace overrides where policy differs |
| P4.4 | backend | Classification tuning from real data | todo | P2.2 | weekly review: flag misclassifications, adjust prompts |

Notes:
- All code is built and tested. System awaits external API credentials to go live.
- P2.4 (Cloudflare Tunnel) is infra config, not code — configure when deploying.
- P2.5/P2.6 (tracking/invoice connectors) have stub interfaces ready — implement when API access available.
- P4.3/P4.4 are enhancement tasks for after live operation begins.
