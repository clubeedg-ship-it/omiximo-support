# omiximo-support — master doc

Retrieve by section anchor. See `CLAUDE.md §7` for the index.

Cadence: `§A` PR-gated · `§B` append-only · `§F` append-only · `§C §D §E §G` overwrite.

---

## §A — Architecture

### §A.1 — Overview

Mirakl customer support automation for Omiximo B.V. (electronics seller on European marketplaces). The system collects customer messages from Mirakl, classifies them by risk/category/language, drafts responses using templates (GREEN) or LLM-augmented knowledge drafting (ORANGE), and queues everything for human review before sending.

Pipeline: `Collector → Classifier → Template/SmartDraft → SafetyRules → PENDING_REVIEW → Human Approve → Send via Mirakl`

The operator sees an email-like inbox. Each thread shows the customer message (with AI summary + English translation), the proposed draft (editable, with back-translation), and a Send button. Nothing sends without a click.

### §A.2 — Tech stack

| Layer | Technology | Notes |
|---|---|---|
| Backend | FastAPI + SQLAlchemy 2.0 async + Pydantic v2 | Python 3.12+ |
| Frontend | React 18 + Vite + Tailwind CSS + shadcn/ui | TypeScript |
| Database | PostgreSQL 16 | Alembic migrations (currently at 007) |
| LLM | OpenRouter API | Classifier: Mistral Nemo, Insight/Draft: Gemini 2.5 Flash |
| Auth | Clerk JWT (not yet configured) + dev bypass via email allowlist | Single-tenant |
| Infra | Docker Compose (api, db, frontend) | Cloudflare Tunnel to support.abbamarkt.nl |
| External | Mirakl REST API (M11 inbox, Connect OAuth2) | Legacy API key auth active |

### §A.3 — Services architecture

| Service | File | Purpose |
|---|---|---|
| `ThreadCollector` | `services/collector.py` | Polls Mirakl for new threads, detects follow-ups, filters noise |
| `MessageFilter` | `services/message_filter.py` | Blocks outbound/system messages at ingestion |
| `MessageClassifier` | `services/classifier.py` | LLM classification → category + risk_level + language |
| `TemplateEngine` | `services/template_engine.py` | Jinja2 slot-filling for GREEN drafts |
| `SmartDraftService` | `services/smart_draft.py` | LLM-augmented drafting for ORANGE using knowledge + history |
| `KnowledgeService` | `services/knowledge_service.py` | CRUD + retrieval for knowledge base entries |
| `SafetyRules` | `services/safety_rules.py` | Hard-coded content validation before send |
| `MessageInsightService` | `services/message_insight.py` | On-demand AI summary + translation |
| `DraftPipeline` | `services/draft_pipeline.py` | Central orchestrator: classify → draft → validate |
| `MiraklClient` | `services/mirakl_client.py` | Mirakl API: fetch threads/orders, send replies (multipart/form-data) |
| `text_clean` | `services/text_clean.py` | HTML stripping for email content |

### §A.4 — API endpoints

```
GET  /health                              — public
GET  /api/v1/threads                      — list with filters, search, pagination
GET  /api/v1/threads/{id}                 — thread detail + messages array
PUT  /api/v1/threads/{id}/approve         — edit draft + send via Mirakl ("Send Reply")
POST /api/v1/threads/{id}/reprocess       — reset FAILED/ESCALATED → PENDING_REVIEW
GET  /api/v1/threads/{id}/insight         — AI summary + translation (cached)
GET  /api/v1/threads/{id}/draft-insight   — draft summary + translation (cached)
POST /api/v1/threads/{id}/translate-draft — back-translation with verification
POST /api/v1/threads/{id}/flag-misclassification
GET  /api/v1/knowledge                    — list knowledge entries
POST /api/v1/knowledge                    — create knowledge entry
PATCH /api/v1/knowledge/{id}              — update
DELETE /api/v1/knowledge/{id}             — soft-delete
POST /api/v1/webhooks/mirakl             — HMAC auth, not Clerk
```

### §A.5 — Workflow behaviour (config toggles in `.env`)

| Setting | Default | Effect |
|---|---|---|
| `AUTO_SEND_ENABLED` | `False` | When False, ALL threads stay in PENDING_REVIEW for human approval |
| `SLA_AUTO_ESCALATE_ENABLED` | `False` | When False, threads never auto-disappear from inbox |

These are the only two "mode switches" in the system. Everything else is code-level.

### §A.6 — Mirakl send_reply format

Both Connect and Legacy paths use `multipart/form-data` with a `message_input` JSON part:
- Legacy (M11): `message_input = {"body": "...", "to": [{"type": "CUSTOMER"}]}`
- Connect: `message_input = {"body": "..."}` → endpoint `/conversations/{id}/messages`

---

## §B — Decisions (append-only)

### 2026-05-09 · D-001 · Templates first, LLM classifies
**Decision:** LLM determines category/risk/language. Templates render GREEN responses. LLM freeform only for ORANGE fallback.
**Rationale:** Controlled quality for auto-send; LLM creativity only where human reviews it.

### 2026-05-09 · D-002 · Multi-marketplace from day one
**Decision:** `marketplace_accounts` table with per-account keys, SLA, template sets.
**Rationale:** Omiximo sells on MediaMarkt, Boulanger, Carrefour, Pixmania.

### 2026-05-09 · D-003 · Safety rules are code invariants
**Decision:** Hard blocks in `safety_rules.py`, not configurable. No refund promises, no return approvals, no fake delivery claims, no external routing.
**Rationale:** Legal protection. These are not business preferences — they are operational constraints.

### 2026-05-09 · D-004 · Audit everything
**Decision:** Every pipeline step writes to `audit_log`.
**Rationale:** Traceability for marketplace disputes and internal review.

### 2026-05-09 · D-005 · Insight is on-demand (D6)
**Decision:** AI summary/translation generated lazily via `/insight` endpoint, not in the pipeline.
**Rationale:** Pipeline must not block on LLM availability. Dashboard works even if LLM is down.

### 2026-05-09 · D-006 · Editable translation with back-translation (D7)
**Decision:** Reviewer edits English draft → `/translate-draft` translates back with self-verify.
**Rationale:** Reviewer works in English; customer gets their language. Binary correction flag, not confidence score.

### 2026-05-19 · D-007 · Kill auto-send and SLA auto-escalation
**Decision:** `AUTO_SEND_ENABLED=False`, `SLA_AUTO_ESCALATE_ENABLED=False`. All threads require human approval. Nothing auto-disappears.
**Rationale:** Operator wants email-inbox UX — see messages, see AI draft, click Send. No hidden automation.

### 2026-05-19 · D-008 · RED threads stay in inbox
**Decision:** RED-classified threads go to PENDING_REVIEW (no draft), not ESCALATED.
**Rationale:** ESCALATED was functionally identical to PENDING_REVIEW but hidden from inbox. Removed the distinction.

### 2026-05-19 · D-009 · Knowledge base with pg_trgm, not pgvector
**Decision:** `knowledge_entries` table with JSON tags + full-text search. No embeddings.
**Rationale:** <500 entries, deterministic retrieval, operator-debuggable. Embeddings are V2 if needed.

### 2026-05-19 · D-010 · Mirakl send uses multipart/form-data
**Decision:** `send_reply` sends `multipart/form-data` with `message_input` JSON part, not `application/json`.
**Rationale:** Mirakl API returned 415 on all 1233 auto-send attempts with JSON. Multipart is the documented format.

### 2026-05-19 · D-011 · Strip HTML from email content
**Decision:** `text_clean.py` (backend) and `stripHtml` (frontend) remove Outlook/Gmail HTML noise before LLM calls and UI previews.
**Rationale:** Mirakl threads contain raw HTML from email clients. LLM wastes tokens on markup; UI shows `<html><head>` noise.

---

## §C — Roadmap & open questions

### §C.1 — Completed
- Central inbox + draft generation
- Safe auto-replies for Green (now gated behind toggle)
- SLA monitoring (now disabled, badge-only)
- Reporting dashboard
- Clerk auth middleware (code ready, credentials not configured)
- Knowledge base (8 seed entries)
- Smart ORANGE drafting (LLM + knowledge + history)
- Conversation threading (multi-message support)
- Message filter (blocks outbound/system noise)
- Mirakl multipart send fix

### §C.2 — Not yet done
- Carrier tracking connector (PostNL/MyParcel/FedEx) — needs API credentials
- Invoice connector (EasyBill) — needs API credentials
- Clerk auth configuration — needs Clerk app creation
- Mirakl Connect OAuth credentials — needs Mirakl onboarding
- Classifier category additions: `cancellation_request`, `paypal_dispute`
- Knowledge base admin UI page

### §C.3 — Open questions
- OQ-1: Stay on dev-bypass auth (single user, domain allowlist) or set up Clerk?
- OQ-2: When to enable auto-send for GREEN? After building confidence from manual approvals?
- OQ-3: Carrier tracking integration timeline — waiting on PostNL/MyParcel API access

---

## §D — Database schema

```
marketplace_accounts: id, marketplace, shop_id, api_key_encrypted, base_url, sla_hours, template_set, is_active
support_threads: id, mirakl_thread_id, mirakl_order_id, marketplace_account_id(FK), customer_language, category, risk_level, status, operator_required, customer_message, message_summary, translated_message, draft_summary, draft_translated, drafted_response, tracking_status, invoice_status, response_deadline, message_count, last_customer_message_at, created_at, updated_at
thread_messages: id, thread_id(FK), direction(INBOUND/OUTBOUND), author_type(CUSTOMER/SHOP_USER/OPERATOR/SYSTEM), body, sequence_number, created_at
audit_log: id, thread_id(FK), action, actor, detail_json, created_at
response_templates: id, marketplace_account_id(FK nullable), category, language, template_body, is_active
classification_flags: id, thread_id(FK), correct_category, correct_risk_level, correct_language, reason, reviewed, created_at
knowledge_entries: id, entry_type(policy/faq/product_info/marketplace_rule), title, content, category_tags(JSON), marketplace_tags(JSON), language, is_active, created_at, updated_at
```

Migrations: 001 initial → 002 flags → 003 api_key optional → 004 message insight → 005 draft insight → 006 knowledge → 007 thread_messages

---

## §E — Handoff (current next-step)

> Overwrite per session.

**Status:** System is functionally complete and deployed. 404 backend tests, 43 frontend tests, all passing. 97 real customer threads in inbox at PENDING_REVIEW. DB cleaned of 1567 noise threads (invoice emails, Zoho notifications, duplicates).

**What was built this session:**
1. Fixed Mirakl 415 send bug (multipart/form-data)
2. Fixed marketplace_name template slot crash
3. Added thread reprocess endpoint + bulk script
4. Added message filter (blocks outbound/system noise at ingestion)
5. Built knowledge base (model, API, service, 8 seed entries, migration 006)
6. Built smart ORANGE drafting (LLM + knowledge + historical examples)
7. Built conversation threading (thread_messages table, backfill, frontend timeline, migration 007)
8. Killed auto-send + SLA auto-escalation (workflow toggles in config.py)
9. Simplified UI: single "Send Reply" button, no escalate, no approval dialogs
10. Fixed operator_required blocking edit/send
11. Collapsed SLA alerts banner (popover instead of full-page)
12. Added HTML stripping (text_clean.py + frontend stripHtml)

**Blockers:**
1. **Mirakl credentials** — Connect OAuth (MIRAKL_CONNECT_CLIENT_ID/SECRET) not configured. Using legacy per-account API key. Polling may fail without valid creds.
2. **Clerk auth** — Code installed but no Clerk app created. Running in dev-bypass mode (email domain allowlist). Works for single user.

**What matters now:**
1. Open the dashboard at `https://support.abbamarkt.nl` — verify 97 threads visible
2. Open a thread → edit draft → click Send Reply → verify it reaches Mirakl
3. If send works: the system is production-ready for manual operation
4. If Mirakl rejects: check API key validity, check response in browser console

---

## §F — History (append-only)

### §F.1 — Milestone log
- 2026-05-09 — Project bootstrapped from fastapi/full-stack-fastapi-template
- 2026-05-09 — Phase 1-4 complete: inbox, classification, templates, auto-send, safety rules, dashboard
- 2026-05-09 — 1683 threads collected from MediaMarktSaturn (bulk import)
- 2026-05-09 — Draft insight, translation, and back-translation features added
- 2026-05-19 — Fixed 415 send bug, template slot bug, added knowledge base + smart drafting
- 2026-05-19 — Built conversation threading (multi-message), message filter
- 2026-05-19 — Workflow simplification: killed auto-send/SLA crons, simplified UI
- 2026-05-19 — Cleaned DB: 1567 noise threads removed, 19 duplicates removed, 97 real threads remain

### §F.2 — Durable lessons
- Mirakl message API requires multipart/form-data, not JSON — cost 1233 failed auto-sends before discovery
- 92% of initially collected threads were Omiximo's own outbound invoice emails — the collector must filter by message direction at ingestion time
- SLA auto-escalation that hides threads from the inbox is worse than no SLA monitoring — operator can't find their threads
- "ESCALATED" status is functionally identical to "PENDING_REVIEW" when all messages need human approval — simplify to one status
- operator_required blocking edit/send makes no sense when everything requires human approval — the flag is informational only
- Jinja2 StrictUndefined + missing safe_context defaults = silent production failures — always include all template vars in defaults
- HTML email content (Outlook, Gmail) in Mirakl threads must be stripped before LLM calls — wastes tokens and confuses summaries

---

## §G — Retrieval

### §G.1 — Section extract
```bash
sed -n '/^## §A/,/^## §B/p' PROJECT.md    # architecture
sed -n '/^## §B/,/^## §C/p' PROJECT.md    # decisions
sed -n '/^## §C/,/^## §D/p' PROJECT.md    # roadmap + OQs
sed -n '/^## §D/,/^## §E/p' PROJECT.md    # database schema
sed -n '/^## §E/,/^## §F/p' PROJECT.md    # handoff
sed -n '/^## §F/,/^## §G/p' PROJECT.md    # history
sed -n '/^## §G/,$p'        PROJECT.md    # retrieval
```

### §G.2 — Decision lookup
```bash
grep -n "^### .*D-[0-9]" PROJECT.md
```

### §G.3 — CLI quick reference
```bash
docker compose up -d                                   # start all
docker compose exec api alembic upgrade head           # run migrations
docker compose exec api python -m scripts.seed_knowledge  # seed KB
docker compose exec api python -m scripts.reprocess_failed --limit 50  # reset stuck threads
cd backend && uv run python -m pytest tests/ -q        # backend tests
cd frontend && npm run build && npm test -- --run       # frontend tests
docker compose restart api                              # pick up .env changes
```

### §G.4 — External
- GitHub: `clubeedg-ship-it/omiximo-support`
- Frontend: https://support.abbamarkt.nl
- API: https://api-support.abbamarkt.nl
