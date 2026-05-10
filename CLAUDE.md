# CLAUDE.md — Omiximo Support Automation

## What this is
Semi-automated Mirakl customer support system. Collects messages from multiple Mirakl marketplace accounts, links to order data, classifies risk, drafts responses using approved templates, and only auto-sends verified safe (Green) replies. Orange = human-approved draft. Red = manual only.

## Stack
- **Backend:** FastAPI, SQLAlchemy, Pydantic, Alembic
- **Frontend:** React, Vite, Tailwind CSS, shadcn/ui
- **Database:** PostgreSQL
- **Infra:** Docker Compose (api, db, frontend), Cloudflare Tunnel for webhook ingress
- **Base template:** `fastapi/full-stack-fastapi-template`
- **Auth:** Clerk (JWT + JWKS), single-tenant email allowlist
- **LLM:** OpenRouter (classifier: Claude Sonnet, insight/translation: Gemini 2.5 Flash)
- **External APIs:** Mirakl REST API (M11 inbox), carrier tracking APIs (Phase 2), invoice APIs (Phase 2)

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

### D6: Insight is on-demand, not pipeline-blocking
Message summary/translation and draft summary/translation are generated lazily via dedicated API endpoints (GET /insight, GET /draft-insight), not during the classify→draft→send pipeline. Results are cached in DB columns. If the LLM is unavailable, the dashboard and review UI still work — insight cards show "unavailable" gracefully.

### D7: Editable translation with back-translation verification
Reviewers can edit the English translation of a drafted response, then POST /translate-draft translates it back to the customer's language with a two-step LLM pass (translate + self-verify). The verification is binary (correction_made bool), not a confidence score. The translated result is not auto-applied — the reviewer clicks "Apply to draft" explicitly. The existing approve endpoint with drafted_response_override is the write path.

### D8: Clerk auth is single-tenant
All /api/v1/* routes require a valid Clerk JWT. Authorization is via ALLOWED_ADMIN_EMAILS or ALLOWED_EMAIL_DOMAIN. The webhook endpoint uses HMAC auth (Mirakl can't present Clerk tokens). Production startup fails if auth config is incomplete.

## Database tables (core)

```
marketplace_accounts: id, marketplace, shop_id, api_key_encrypted, base_url, sla_hours, template_set, is_active
support_threads: id, mirakl_thread_id, mirakl_order_id, marketplace_account_id(FK), customer_language, category, risk_level(GREEN/ORANGE/RED), status(PENDING_REVIEW/APPROVED/SENT_AUTO/ESCALATED/FAILED), operator_required(bool), customer_message, message_summary(nullable), translated_message(nullable), draft_summary(nullable), draft_translated(nullable), drafted_response, tracking_status, invoice_status, response_deadline, created_at, updated_at
audit_log: id, thread_id(FK), action, actor(system/user_id), detail_json, created_at
response_templates: id, marketplace_account_id(FK nullable), category, language(nl/en/fr/de), template_body, is_active
classification_flags: id, thread_id(FK), correct_category, correct_risk_level, correct_language, reason, reviewed, created_at
```

## API endpoints (key)

```
GET  /health                              — public
GET  /api/v1/threads                      — list with filters, search, pagination
GET  /api/v1/threads/{id}                 — thread detail
PUT  /api/v1/threads/{id}/approve         — approve + send via Mirakl
PUT  /api/v1/threads/{id}/escalate        — manual escalation
GET  /api/v1/threads/{id}/insight         — AI summary + translation (cached)
GET  /api/v1/threads/{id}/draft-insight   — draft summary + translation (cached)
POST /api/v1/threads/{id}/translate-draft — back-translation with verification
POST /api/v1/threads/{id}/flag-misclassification
POST /api/v1/webhooks/mirakl             — HMAC auth, not Clerk
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
cd backend && uv run pytest tests/ -q
cd frontend && npm run lint && npm test -- --run && npm run build
```

## Required env/config

### Backend (.env)
```
ENVIRONMENT=development|production
FERNET_KEY=<generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
CLERK_ISSUER=https://<your-app>.clerk.accounts.dev
CLERK_JWKS_URL=https://<your-app>.clerk.accounts.dev/.well-known/jwks.json
ALLOWED_ADMIN_EMAILS=admin@omiximo.nl
LLM_API_KEY=<openrouter-key>
MIRAKL_CONNECT_CLIENT_ID=<mirakl-connect-id>
MIRAKL_CONNECT_CLIENT_SECRET=<mirakl-connect-secret>
MIRAKL_WEBHOOK_SECRET=<webhook-hmac-secret>
```

### Frontend (.env)
```
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
```

### Dev bypass (local only)
```
ALLOW_INSECURE_DEV_AUTH_BYPASS=true
DEV_AUTH_BYPASS_EMAIL=admin@omiximo.nl
VITE_ALLOW_INSECURE_DEV_AUTH_BYPASS=true
```

## Alembic migrations
```
001 — initial schema (4 core tables)
002 — classification_flags table
003 — make api_key optional (Connect mode)
004 — message_summary + translated_message columns
005 — draft_summary + draft_translated columns
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
- Put insight/translation in the classification pipeline — it's on-demand only (D6)
- Auto-apply translated drafts — reviewer must click "Apply to draft" (D7)
- Cache back-translation results — drafts are mutable (D7)
- Use hardcoded per-language logic in translation prompts — pass language as parameter

>> EXTREMELY IMPORTANT <<<

NO HACKS. The user is EXTREMELY concerned about code quality, much more so than
immediate results. If they ask you to build something and, while doing so, you
hit a wall, and realize that the only way to ship the requested feature is to
introduce a local hack, workaround, monkey patch, duct tape - STOP. STOP
IMMEDIATELY. Either fix the underlying flaw that blocked you in a ROBUST, WELL
DESIGNED, PRODUCTION READY manner, or be honest that the prompt can't be
completed without hacks.

To make it very clear:

- DO NOT INTRODUCE HACKS IN THE CODEBASE.

- DO NOT COMMIT CODE THAT COULD BREAK THINGS LATER.

- DO NOT COMMIT PARTIAL SOLUTIONS OR WORKAROUNDS.

THIS IS VERY IMPORTANT.
THIS IS VERY IMPORTANT.
THIS IS VERY IMPORTANT.

The author appreciates honestly and he WILL be glad and thankful if you respond
a request with "I couldn't complete your request because the repository lacked
support for X". He will be even happier if you go ahead and update the repo to
provide the necessary support in a well designed, robust way. But he will be
VERY ANGRY if, while attempting to implement a feature, you introduce a
workaround that will potentially break things later.

NEVER introduce hacks in the codebase.

Also assume that none of the code you're working in is in production, so,
backwards compatibility is NOT IMPORTANT. If you find something that is poorly
designed and fixing it would require breaking existing APIs or behavior, DO SO.
Do it properly rather than preserving a flawed design. Prioritize clarity,
correctness, and maintainability over compatibility with existing code.

Core values:
- ABSOLUTE code quality over speed of delivery.
- Correctness over convenience.
- Clarity over cleverness.
- Maintainability over short-term productivity.
- Robust design over quick fixes.
- Simplicity over complexity.
- Doing it right over doing it now.
- Honesty above everything.

After every change you make, provide a clear, honest report on ANY change that
you are not confident about and that could be considered a fragile hack.
