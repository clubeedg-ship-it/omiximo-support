# CLAUDE.md — Omiximo Support Automation

## What this is
Semi-automated Mirakl customer support system. Collects messages from multiple Mirakl marketplace accounts, links to order data, classifies risk, drafts responses using approved templates, and only auto-sends verified safe (Green) replies. Orange = human-approved draft. Red = manual only.

## Stack
- **Backend:** FastAPI, SQLAlchemy, Pydantic, Alembic
- **Frontend:** React, Vite, Tailwind CSS, shadcn/ui
- **Database:** PostgreSQL
- **Infra:** Docker Compose (api, db, frontend), Cloudflare Tunnel for webhook ingress
- **Base template:** `fastapi/full-stack-fastapi-template`
- **External APIs:** Mirakl REST API, Cloud LLM (classification only), carrier tracking APIs (Phase 2), invoice APIs (Phase 2)

## Key architecture decisions

### D1: Templates first, LLM classifies — LLM does NOT generate responses
The LLM determines: category, risk_level, language. A template engine renders the actual response using approved templates + order data slots. LLM freeform drafting is only allowed for Orange cases as a fallback.

### D2: Multi-marketplace from day one
`marketplace_accounts` table holds per-account Mirakl API keys, shop_id, marketplace name, SLA hours, and template set identifier. Thread collector iterates all active accounts.

### D3: Safety rules are code invariants, not config
`safety_rules.py` contains hard blocks that run before any auto-send:
- Never auto-send refund promises
- Never auto-approve returns
- Never auto-reply to marketplace/operator messages (`operator_required=True`)
- Never claim delivery without verified carrier status
- Never auto-reject warranty/defect claims
- Never route customers outside marketplace message channel

### D4: Audit everything
Every automated decision, draft generation, approval, send, and failure gets a row in `audit_log`.

### D5: Connectors are pluggable
Abstract `ConnectorBase.fetch_context(order_id) -> dict`. Mirakl is Phase 1. Tracking (PostNL/MyParcel/FedEx) and invoice (EasyBill) are Phase 2.

## Database tables (core)

```
marketplace_accounts: id, marketplace, shop_id, api_key_encrypted, base_url, sla_hours, template_set, is_active
support_threads: id, mirakl_thread_id, mirakl_order_id, marketplace_account_id(FK), customer_language, category, risk_level(GREEN/ORANGE/RED), status(PENDING_REVIEW/APPROVED/SENT_AUTO/ESCALATED/FAILED), operator_required(bool), customer_message, drafted_response, tracking_status, invoice_status, response_deadline, created_at, updated_at
audit_log: id, thread_id(FK), action, actor(system/user_id), detail_json, created_at
response_templates: id, marketplace_account_id(FK nullable), category, language(nl/en/fr/de), template_body, is_active
```

## CLI quick reference

```bash
# Start infra
docker compose up -d

# Run migrations
docker compose exec api alembic upgrade head

# Backend dev
cd backend && uvicorn app.main:app --reload --port 8000

# Frontend dev
cd frontend && npm install && npm run dev

# Tests
cd backend && pytest tests/ -v
```

## Supported languages
Dutch (nl), English (en), French (fr), German (de)

## Marketplaces (known)
MediaMarkt, Boulanger, Carrefour, Pixmania

## Do not
- Let the LLM generate freeform responses for Green cases — templates only
- Auto-send anything without safety_rules validation passing
- Store Mirakl API keys in plaintext — use Fernet encryption
- Assume single marketplace — always scope by marketplace_account_id
- Skip audit_log writes — every action gets logged
- Reply to operator/marketplace messages automatically — ever

