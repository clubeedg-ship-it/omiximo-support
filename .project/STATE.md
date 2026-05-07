# STATE

repo: clubeedg-ship-it/omiximo-support
branch: main
phase: pre-scaffolding
queue_head: P1.1 (clone fastapi template + docker compose up)

runtime:
  backend: docker compose (postgres, api)
  frontend: docker compose (vite dev server) or local npm run dev
  infra: Cloudflare Tunnel → api:8000 (not configured yet)

truths:
  - LLM is a classifier, not a response generator (D1)
  - templates are the response authority for Green cases
  - safety_rules.py is a hard gate before any auto-send
  - all threads scoped to marketplace_account_id (D2)
  - audit_log is mandatory for every automated action (D4)
  - auto-send is OFF until Phase 2 validation period completes
  - operator messages are always Red + operator_required=True

blockers:
  - need Mirakl API credentials for at least one marketplace account
  - need to choose Cloud LLM provider (Claude API recommended)
  - Cloudflare Tunnel config not set up yet

open_questions:
  - which carrier tracking APIs are available? (PostNL/MyParcel/FedEx)
  - which invoice tool? (EasyBill assumed from client doc)
  - Mirakl webhook format — need sample payload or docs access
  - auth for dashboard — Clerk, simple JWT, or basic auth for v1?

retrieval:
  project_context: CLAUDE.md
  state: .project/STATE.md
  queue: .project/QUEUE.md
