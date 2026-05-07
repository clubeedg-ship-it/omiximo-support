# STATE

repo: clubeedg-ship-it/omiximo-support
branch: main
phase: all-code-complete
queue_head: BLOCKED — awaiting Mirakl API credentials + LLM API key

runtime:
  backend: docker compose (postgres, api) or local uvicorn
  frontend: docker compose (vite dev server) or local npm run dev
  infra: Cloudflare Tunnel → api:8000 (not configured yet)

completed:
  - P1.1: Scaffold + Docker Compose ✓
  - P1.2: DB schema (4 tables, Alembic migration) ✓
  - P1.3: Mirakl thread collector ✓
  - P1.4: Order data enrichment ✓
  - P1.5: Classification engine (LLM) ✓
  - P1.6: Template engine + draft generation ✓
  - P1.7: Safety rules module (6 invariants) ✓
  - P1.8: API endpoints (threads, accounts, templates, health) ✓
  - P1.9: Triage dashboard (DataTable) ✓
  - P1.10: Review pane (split view) ✓
  - P1.11: Seed templates (7 categories × 4 languages) ✓
  - P2.1: Auto-send validation rules ✓
  - P2.2: Auto-send execution path (SELECT FOR UPDATE SKIP LOCKED) ✓
  - P2.3: Webhook ingestion endpoint (HMAC validated) ✓
  - P3.1: SLA deadline monitoring + auto-escalation ✓
  - P3.2: Missing tracking/invoice alerts ✓
  - P3.3: Alert banners on dashboard ✓
  - P4.1: Reporting endpoints (summary + timeline) ✓
  - P4.2: Reporting dashboard (charts, no external lib) ✓
  - P4.3: Marketplace-specific template overrides ✓
  - P4.4: Classification tuning (flag/resolve workflow + UI) ✓

truths:
  - LLM is a classifier, not a response generator (D1)
  - templates are the response authority for Green cases
  - safety_rules.py is a hard gate before any auto-send
  - all threads scoped to marketplace_account_id (D2)
  - audit_log is mandatory for every automated action (D4)
  - auto-send runs in background loop every MIRAKL_POLL_INTERVAL_SECONDS
  - SLA auto-escalation runs every 15 minutes
  - operator messages are always Red + operator_required=True

blockers:
  - need Mirakl API credentials for at least one marketplace account
  - need LLM API key (Claude API) for classification
  - Cloudflare Tunnel config not set up yet (needed for webhooks)

open_questions:
  - which carrier tracking APIs are available? (PostNL/MyParcel/FedEx)
  - which invoice tool? (EasyBill assumed from client doc)
  - auth for dashboard — Clerk, simple JWT, or basic auth for v1?

retrieval:
  project_context: CLAUDE.md
  state: .project/STATE.md
  queue: .project/QUEUE.md
