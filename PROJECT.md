# omiximo-support — master doc

Retrieve by section anchor. See `CLAUDE.md §7` for the index.

Cadence: `§A` PR-gated · `§B` append-only · `§F` append-only · `§C §D §E §G` overwrite.

---

## §A — Architecture

### §A.1 — Overview

Mirakl customer support automation for Omiximo B.V. (electronics seller on European marketplaces). The system collects customer messages from Mirakl, classifies them by risk/category/language, and produces a reply for human approval before anything is sent.

Two drafting paths exist, switched by `AGENT_ENABLED`:
- **Legacy (default, AGENT_ENABLED=False):** `Collector → Classifier → Template (GREEN) / SmartDraft (ORANGE) → SafetyRules → PENDING_REVIEW → human Approve in the dashboard → Send via Mirakl`. Template-first; the LLM only augments ORANGE drafts — which is why replies were generic "we're looking into it" holding messages.
- **Agent (AGENT_ENABLED=True):** `Collector → Classifier → AgentRunner (tool-calling loop: reads real order data, writes the resolution itself) → proposes one action → Telegram Approve/Deny → execute via Mirakl`. The agent acts as the rep; nothing leaves without a human tapping Approve.

The operator sees an email-like inbox (dashboard) AND, with the agent, a Telegram activity channel with Approve/Deny cards.

### §A.2 — Tech stack

| Layer | Technology | Notes |
|---|---|---|
| Backend | FastAPI + SQLAlchemy 2.0 async + Pydantic v2 | Python 3.12; httpx for all outbound (OpenRouter, Telegram, Mirakl) |
| Frontend | React 18 + Vite + Tailwind + shadcn/ui | TypeScript; built to static `dist/`, served by nginx |
| Database | PostgreSQL 16 | Alembic migrations **at 011** |
| LLM | OpenRouter API | Classifier: Mistral Nemo; Insight/SmartDraft: Gemini 2.5 Flash; Agent: `AGENT_MODEL` (Gemini 2.5 Flash, tool-calling) |
| Auth | Clerk JWT (not configured) + dev bypass via email allowlist | Single-tenant; Telegram webhook auth is a secret-token header, not Clerk |
| Infra | **k3s** (namespace `omiximo-support`) | api Deployment + db StatefulSet(PVC) + frontend Deployment; host nginx → NodePorts; NOT docker-compose |
| Messaging | Telegram Bot API | `@omiximo_support_bot` → activity channel + Approve/Deny gate |
| External | Mirakl REST API (M11 inbox, Connect OAuth2) | Legacy per-account API key auth active (key in DB, Fernet-encrypted); Connect creds not set |

### §A.3 — Services architecture

| Service | File | Purpose |
|---|---|---|
| `ThreadCollector` | `services/collector.py` | Polls Mirakl for new threads, filters noise, posts 🆕 to the Telegram activity channel |
| `MessageFilter` | `services/message_filter.py` | Blocks outbound/system messages at ingestion (no per-message audit row) |
| `MessageClassifier` | `services/classifier.py` | LLM classification → category + risk_level + language |
| `TemplateEngine` | `services/template_engine.py` | Jinja2 slot-filling for GREEN drafts |
| `SmartDraftService` | `services/smart_draft.py` | LLM-augmented ORANGE drafting (legacy path) using knowledge + history |
| `KnowledgeService` | `services/knowledge_service.py` | CRUD + retrieval for knowledge base entries |
| `SafetyRules` | `services/safety_rules.py` | Hard-coded content validation before send |
| `DraftPipeline` | `services/draft_pipeline.py` | Orchestrator: classify → (agent OR template) → validate; routes to the agent when `AGENT_ENABLED` |
| `AgentRunner` | `services/agent/runner.py` | Tool-calling loop; thread-scoped memory; narrates steps to Telegram |
| agent tools | `services/agent/tools.py` | Read tools (get_order/tracking/invoice, search_knowledge) + approval-gated send_reply/escalate |
| fake fixtures | `services/agent/fake_mirakl.py` | Example order data (real format) for `AGENT_FAKE_MIRAKL` test mode |
| `TelegramService` | `services/telegram.py` | Activity posts + Approve/Deny inline cards; no-op without a token |
| connectors | `services/connectors/{mirakl,tracking,invoice}.py` | Order context. `mirakl` is live; `tracking`/`invoice` are still `{}` stubs |
| `MiraklClient` | `services/mirakl_client.py` | Mirakl API: fetch threads/orders, send replies (multipart/form-data) |
| `text_clean` | `services/text_clean.py` | HTML stripping for email content |

### §A.4 — API endpoints

```
GET  /health                              — public, k8s probe target
GET  /api/v1/threads                      — list with filters, search, pagination
GET  /api/v1/threads/{id}                 — thread detail + messages array
PUT  /api/v1/threads/{id}/approve         — edit draft + send via Mirakl ("Send Reply")
POST /api/v1/threads/{id}/reprocess       — reset FAILED/ESCALATED → PENDING_REVIEW
GET  /api/v1/threads/{id}/insight         — AI summary + translation (cached)
GET  /api/v1/threads/{id}/draft-insight   — draft summary + translation (cached)
POST /api/v1/threads/{id}/translate-draft — back-translation with verification
POST /api/v1/threads/{id}/flag-misclassification
GET/POST/PATCH/DELETE /api/v1/knowledge   — knowledge base CRUD
POST /api/v1/webhooks/mirakl              — HMAC auth, not Clerk
POST /api/v1/telegram/webhook             — Approve/Deny callbacks; secret-token header; unprotected
POST /api/v1/agent/test-run               — fire a synthetic thread through the agent; 403 unless AGENT_FAKE_MIRAKL
```

### §A.5 — Workflow behaviour (config toggles, in the `omiximo-env` secret)

| Setting | Default | Effect |
|---|---|---|
| `AUTO_SEND_ENABLED` | `False` | When False, ALL threads stay in PENDING_REVIEW for human approval |
| `SLA_AUTO_ESCALATE_ENABLED` | `False` | When False, threads never auto-disappear from inbox |
| `AGENT_ENABLED` | `False` | When True, non-RED threads are handled by the tool-calling agent (Telegram-gated) instead of the template path |
| `AGENT_FAKE_MIRAKL` | `False` | Test mode: read tools return fake fixtures, sends simulated; enables `/agent/test-run`. **Currently True in the cluster for polishing.** |
| `AGENT_TELEGRAM_VERBOSE` | `True` | Narrate each tool call into the activity channel |
| `AGENT_MODEL` / `AGENT_MAX_STEPS` | gemini-2.5-flash / 6 | Agent LLM + max tool-call iterations |

### §A.6 — Mirakl send_reply format

Both Connect and Legacy paths use `multipart/form-data` with a `message_input` JSON part:
- Legacy (M11): `message_input = {"body": "...", "to": [{"type": "CUSTOMER"}]}`
- Connect: `message_input = {"body": "..."}` → endpoint `/conversations/{id}/messages`

### §A.7 — Deployment (k3s)

IaC lives in `k8s/` (committed). `kubectl apply -k k8s/`.
- `db` — StatefulSet, postgres:16, PVC `pgdata-db-0` (local-path, 8Gi), autovacuum-tuned. Headless Service `db:5432`.
- `api` — Deployment, `replicas: 1`, `Recreate`. initContainers: `wait-for-db` (pg_isready) + `migrate` (`alembic upgrade head`). Probes on `/health`. Service NodePort **30800**.
- `frontend` — Deployment, 2 replicas, nginx static. Service NodePort **30173**.
- Host nginx (`/etc/nginx/sites-available/support.abbamarkt.nl.conf`) proxies `api-support.abbamarkt.nl → :30800`, `support.abbamarkt.nl → :30173`. An edge (returns 502 when the origin VM is down) fronts the domains.
- Images built locally (`docker build`) → imported into containerd (`k3s ctr images import`); `imagePullPolicy: IfNotPresent`, tag `:prod`. No registry.
- Secrets created out-of-band: `omiximo-env` (app), `omiximo-db` (postgres). Never committed.

### §A.8 — Autonomous agent (Phase 1)

- `AgentRunner.run_for_thread` builds messages = system prompt + the thread's OWN `thread_messages` only (scoped memory — no cross-thread/global state), then loops up to `AGENT_MAX_STEPS` calling OpenRouter with `TOOL_SCHEMAS`.
- Read tools (`get_order` live via connector / `get_tracking`,`get_invoice` stubs / `search_knowledge`) execute immediately and feed facts back. `send_reply`/`escalate` do NOT act — they persist an `agent_actions` row (`proposed`) and post a Telegram Approve/Deny card.
- Every step → an `agent_event` row + (verbose) a Telegram narration line.
- `POST /api/v1/telegram/webhook` handles the button: **approve** → execute `send_reply` via Mirakl (or simulate when `AGENT_FAKE_MIRAKL`), flip thread to `SENT_AUTO`, edit card to "✅ Sent"; **deny** → discard. Idempotent against Telegram retries.
- Phase 1 = `send_reply` only. `approve_return`/`issue_refund` are Phase 2 (the gate + webhook dispatch are written generically to slot them in as new `action_type`s).

---

## §B — Decisions (append-only)

Each entry: date · id · title, then Decision / Rationale.

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

### 2026-06-12 · D-012 · Persist full conversation history, render as chat
**Decision:** Ingestion now stores EVERY Mirakl message as a `ThreadMessage` (customer/shop/operator, original timestamp, sender name), keyed by `mirakl_message_id` for idempotent sync (migration 008 adds `mirakl_message_id` + `author_name`). `customer_message` stays the latest inbound customer body for the classifier/draft pipeline. The review page renders the messages as a Mirakl-style chat with an Info sidebar.
**Rationale:** Old ingestion kept only the latest customer message and discarded the rest. Existing 87 threads rebuilt by re-pulling from Mirakl (`scripts/backfill_thread_history.py`) — all 87 recovered, 534 messages, 0 missing.

### 2026-06-12 · D-013 · Full inbox with live reply-state, sorted by activity
**Decision:** The app is now a complete inbox, not just an unanswered-queue.
- **Filter relaxed** (`message_filter`): reject only shop-only noise, so threads we already replied to stay visible (87 → 111).
- **`reply_state`** (migration 009) derived from Mirakl `metadata.shop_reply_needed_since` + `last_sender`: NEEDS_REPLY / AWAITING_CUSTOMER / RESOLVED. The draft pipeline now ONLY processes NEEDS_REPLY threads.
- **`last_activity_at`** (migration 010) from Mirakl `metadata.last_message_date`; default dashboard sort.
- **Audit spam fixed**: the collector no longer writes a `message_filtered` audit row per noise thread per poll.
**Rationale:** User couldn't see handled/resolved threads, and "this week's" activity was buried by creation-date sort.

### 2026-06-23 · D-014 · Reliability hardening + k8s infrastructure-as-code
**Decision:** Move off dev-mode-in-prod and put the deployment in git. Production Dockerfiles (backend: multi-stage, non-root, no `--reload`, single uvicorn; frontend: `vite build` served by nginx, not the dev server). Full `k8s/` manifests: namespace, api Deployment, **db StatefulSet on a PVC**, frontend Deployment, kustomization, runbook. NodePorts pinned (api 30800, frontend 30173) so host-nginx routing is unchanged.
**Rationale:** The frontend pod was OOMKilled ~21× running the Vite dev server; the backend Dockerfile ran `--reload`; the k8s state existed only in the live cluster (unreproducible); Postgres data sat on an unmanaged hostPath Docker volume. The migration to a PVC StatefulSet also shed 43.4M historical `message_filtered` audit rows (18GB → 10MB) — restored clean, 126 threads + 705 messages intact, with a full pg_dump backup kept.

### 2026-06-23 · D-015 · Autonomous tool-calling agent, gated by Telegram Approve/Deny
**Decision:** Add a native tool-calling agent (`services/agent/`) that pulls real order data and writes the resolution itself as the rep, replacing the template-first path when `AGENT_ENABLED=True`. Every outward action is a `agent_actions` proposal surfaced as a Telegram **Approve/Deny** card; nothing executes without a human tap (`/api/v1/telegram/webhook`). Memory is scoped to the thread's own conversation. New tables `agent_actions` + `agent_events` (migration 011).
**Rationale:** The old pipeline's LLM was straitjacketed (prompt forbade resolving anything) and human-gated only in the dashboard, so every reply was a generic "a human will contact you." The user wants a humanless agent that acts as the human, with a one-tap approval and a managed activity log — Telegram is that control surface.

### 2026-06-23 · D-016 · API pinned to a single replica
**Decision:** `api` Deployment is `replicas: 1` with `strategy: Recreate`.
**Rationale:** `app.main:app`'s FastAPI lifespan starts in-process background loops (mirakl_poller, auto_send_executor, sla_monitor). A second replica would poll Mirakl twice and could send a customer reply twice. Horizontal scaling requires first extracting the schedulers into their own single-replica worker.

### 2026-06-23 · D-017 · Fake-Mirakl test harness for the agent + Telegram flow
**Decision:** `AGENT_FAKE_MIRAKL` makes the read tools return built-in fixtures in the real order format (`fake_mirakl.py`), simulates the send on approve, and enables `POST /api/v1/agent/test-run` to fire a synthetic thread through the full loop into the Telegram channel.
**Rationale:** Polish the agent + Telegram workflow end-to-end with realistic data without touching the live marketplace or flipping `AGENT_ENABLED` on real customer threads.

### 2026-06-28 · D-018 · Telegram operator console (self-contained card + router)
**Decision:** Telegram is the operator console. The approval card is self-contained — classification + order/tracking/knowledge facts + full threaded conversation history (👤 Klant / 🧑‍💼 Wij quotes, newest marked, oldest collapsed into an expandable quote when long) + the proposed reply/escalation — with action-aware buttons (Approve/Deny vs Escalate/Dismiss). Card rendering is a pure, unit-tested module (`services/agent/cards.py`). The webhook is now a router that dispatches button callbacks + slash commands (`/help`, `/status`), acking taps via `answerCallbackQuery`. Roadmap in `docs/superpowers/plans/2026-06-28-telegram-operator-console.md`: F2 Edit draft → F3 Translate (language picker) → F4 cross-thread nav → F5 system cmds.
**Rationale:** The reviewer must see everything they act on in one message, with prior conversation visible in-place. A router makes adding Edit/Translate/nav handlers clean instead of bolting onto a single-purpose webhook. `context_json` + `telegram_sessions` (migration 012) are deferred to F2 — only needed once cards re-render after the run.

### 2026-06-28 · D-019 · Phase 2 connectors source everything from Mirakl (+ fetch_order 410 fix)
**Decision:** Order facts, tracking, and invoice all derive from the single Mirakl order response — no external carrier (PostNL/MyParcel) or invoicing (EasyBill) integration. `connectors/mirakl.py` holds pure extractors `order_facts` / `tracking_facts` / `invoice_facts`; `Tracking`/`InvoiceConnector` take the account and slice the same order. Critically, `_LegacyMiraklClient.fetch_order` was calling `GET /api/orders/{id}` which returns **410** — real order data never loaded — now fixed to the OR11 list form `GET /api/orders?order_ids=`. Verified live: real orders return status/item/amount/carrier/tracking#/tracking_url/has_invoice.
**Rationale:** One credential set already configured, one fetch per order, no new vendor integrations. The 410 fix is a go-live prerequisite — without it both the agent and the legacy template pipeline got empty order context. Full invoice PDF (Mirakl documents endpoint) and live carrier events are deferred.

### 2026-06-28 · D-020 · Go-live: agent enabled on real threads, safety-gated
**Decision:** Flipped `AGENT_ENABLED=true` + `AGENT_FAKE_MIRAKL=false` (omiximo-env secret). The agent now drafts REAL customer threads as human-gated approval cards. Before flipping, closed the critical gap that the agent path bypassed `safety_rules`: every `send_reply` is now validated, violations render a ⚠️ block, the Approve button is withheld (Edit/Deny only), edits re-validate, and the webhook refuses to approve flagged actions. `AUTO_SEND_ENABLED=False` unchanged — nothing sends without a human tap. Verified live: a real German draft posted for a real order; `R3 operator_required` was correctly caught and the card flagged. `register_webhook()` runs on startup (allowed_updates message+callback_query). Backlog not force-processed — only new Mirakl threads flow to the agent.
**Rationale:** Everything safe was built + tested (492 backend tests) + deployed + live-verified. Refund/return agent actions are deliberately NOT built/enabled — they are financial + conflict with D-003 and require explicit sign-off and a safety-rules reconciliation.

---

## §C — Roadmap & open questions

### §C.1 — Completed
- Central inbox + draft generation; safe Green auto-replies (gated behind toggle); SLA monitoring (disabled, badge-only); reporting dashboard.
- Knowledge base; smart ORANGE drafting; conversation threading; message filter; Mirakl multipart send fix.
- Full inbox with reply-state + activity sort (D-012, D-013).
- **Reliability hardening + k8s IaC (D-014):** prod Dockerfiles, `k8s/` manifests, Postgres StatefulSet on a PVC, audit-spam pruned (18GB → 10MB).
- **Autonomous agent Phase 1 (D-015):** tool-calling runner, `agent_actions`/`agent_events` (migration 011), Telegram service + Approve/Deny webhook, pipeline integration. 447 backend tests pass. Gated off (`AGENT_ENABLED=False`).
- **Telegram wired:** bot, group `-5262705193`, webhook registered, secrets stored.
- **Fake-Mirakl test harness (D-017):** deployed with `AGENT_FAKE_MIRAKL=true`; a `test-run` produced a real order-aware Dutch reply as an Approve card.

### §C.2 — Not yet done (next work, prioritized)
1. **Polish the Telegram workflow** with the user (card layout — fold order facts + classification into the approval card; verbosity).
2. **Go-live decision:** flip `AGENT_ENABLED=true` (full catch-up of ~23 unclassified threads, or park the backlog and act only on new threads).
3. **Phase 2 connectors:** `get_tracking` / `get_invoice` are still `{}` stubs — build real Mirakl/carrier endpoints so the agent answers tracking/invoice questions instead of escalating.
4. **Phase 2 actions:** `approve_return` / `issue_refund` via the generic action gate (verify Mirakl OR/refund endpoints for the MediaMarktSaturn key).
5. Clerk auth configuration; Mirakl Connect OAuth credentials.
6. SLA "~3yr overdue" still renders red in the review Info sidebar — apply the dashboard's Historical treatment.
7. Message attachments not captured/served (chat shows text only).

### §C.3 — Open questions
- OQ-1: Stay on dev-bypass auth or set up Clerk?
- OQ-2: When to flip `AGENT_ENABLED` on for real — and full catch-up vs. park-backlog?
- OQ-3: How much authority does the agent get in Phase 2 (can it actually approve returns / issue refunds), given each action is human-gated anyway?
- OQ-4: Investigate the VM's recurring Tailscale drop-outs before leaning on it for the live agent.

---

## §D — Database schema

```
marketplace_accounts: id, marketplace, shop_id, api_key_encrypted, base_url, sla_hours, template_set, is_active
support_threads: id, mirakl_thread_id, mirakl_order_id, marketplace_account_id(FK), customer_language, category, risk_level, status, operator_required, reply_state, customer_message, message_summary, translated_message, draft_summary, draft_translated, drafted_response, tracking_status, invoice_status, response_deadline, message_count, last_customer_message_at, last_activity_at, created_at, updated_at
thread_messages: id, thread_id(FK), direction(INBOUND/OUTBOUND), author_type(CUSTOMER/SHOP_USER/OPERATOR/SYSTEM), author_name, mirakl_message_id, body, sequence_number, created_at
audit_log: id, thread_id(FK), action, actor, detail_json, created_at
agent_actions: id, thread_id(FK), action_type(send_reply/escalate), status(proposed/approved/denied/executed/failed), payload_json, telegram_message_id, decided_by, result_json, created_at, decided_at
agent_events: id, thread_id(FK), event_type(thread_received/tool_call/tool_result/agent_message/proposal_created/action_executed/error), detail_json, created_at
response_templates: id, marketplace_account_id(FK nullable), category, language, template_body, is_active
classification_flags: id, thread_id(FK), correct_category, correct_risk_level, correct_language, reason, reviewed, created_at
knowledge_entries: id, entry_type, title, content, category_tags(JSON), marketplace_tags(JSON), language, is_active, created_at, updated_at
```

Migrations: 001 initial → … → 007 thread_messages → 008 mirakl_message_id/author_name → 009 reply_state → 010 last_activity_at → **011 agent_actions + agent_events**.

---

## §E — Handoff (current next-step)

> Hot state — overwrite per session. YAML.
```yaml
as_of: 2026-06-28
mode: >
  LIVE (D-020), commit 3f02f14, 493 tests. Post-go-live UX fixes from live use:
  safety gating is WARN-ONLY (⚠️ always shows, Approve never withheld — operator
  decides, since every reply is human-reviewed and AUTO_SEND is off); operator
  threads ESCALATE instead of producing a blocked draft; the agent skips
  AWAITING_CUSTOMER/RESOLVED threads (don't draft when we already replied); 🌐
  Translate now renders the WHOLE card (labels + facts + conversation + reply) in
  the chosen language with HTML preserved (translate_html + plain-text fallback).
  --- Go-live baseline: AGENT_ENABLED=true + AGENT_FAKE_MIRAKL=false on k3s — the agent
  drafts REAL customer threads as human-gated approval cards (AUTO_SEND_ENABLED=
  False, nothing sends without a tap). 492 backend tests pass (all TDD), migration
  012 applied. Console (D-018) + Phase 2 Mirakl connectors (D-019) + safety-gating
  of agent replies all built, deployed, live-verified. Live proof: a real German
  draft posted for a real order; safety R3 (operator_required) correctly caught +
  Approve withheld. Webhook auto-registers on startup (message+callback_query).
what_matters: >
  System is live and self-running: the Mirakl poller ingests new threads → agent
  drafts → safety check → approval card → operator taps Approve/Edit/Translate/Deny.
  Watch the channel as real threads arrive. Refund/return actions are intentionally
  NOT built (financial + D-003) — need explicit sign-off + safety reconciliation.
next_actions:
  - Monitor the first real agent cards in the channel; tune drafting/safety if needed.
  - Optional refinements: skip drafting for operator_required threads upfront (currently drafted-then-R3-flagged, same as legacy); edit escalation reasons; multi-operator claim-lock; invoice PDF via Mirakl documents endpoint.
  - When/if wanted (needs your sign-off): approve_return / issue_refund agent actions + safety_rules reconciliation; optional backlog reprocessing of existing PENDING threads.
do_not:
  - Do not bump api replicas or switch to RollingUpdate (in-process schedulers → double-send). D-016.
  - Do not change NodePorts 30800/30173 (host nginx routing) or move Postgres off the PVC.
  - Do not enable real sends without the Telegram Approve gate; do not commit secrets (gitleaks hook will block).
  - Do not re-introduce a per-filtered-message audit row (caused the 43M-row / 18GB bloat).
```

---

## §F — History (append-only)

### §F.1 — Milestone log
- 2026-05-09 — Project bootstrapped from fastapi/full-stack-fastapi-template
- 2026-05-09 — Phase 1-4 complete: inbox, classification, templates, auto-send, safety rules, dashboard
- 2026-05-09 — 1683 threads collected from MediaMarktSaturn (bulk import); draft insight, translation, back-translation added
- 2026-05-19 — Fixed 415 send bug, template slot bug, added knowledge base + smart drafting; conversation threading; message filter; killed auto-send/SLA crons; cleaned DB to ~97 real threads
- 2026-05-21 — Collector uses Mirakl original dates; re-imported 87 threads (2022-2026); UI audit (9 fixes); relative time formatting; rewrote CLAUDE.md + PROJECT.md in §A-§G format
- 2026-06-12 — Full conversation history at ingestion + chat review page + backfill (534 messages); reply_state + last_activity_at; inbox 87→111; stopped per-poll audit spam
- 2026-06-23 — **Reliability hardening + k8s IaC (D-014):** prod Dockerfiles (killed dev servers), `k8s/` manifests, Postgres StatefulSet on a PVC. Migrated off the hostPath DB, pruned 43.4M `message_filtered` audit rows (18GB → 10MB), 126 threads intact, full backup kept.
- 2026-06-23 — **Autonomous agent Phase 1 (D-015/016/017):** tool-calling runner with thread-scoped memory; `agent_actions`/`agent_events` (migration 011); TelegramService + Approve/Deny webhook; pipeline integration; fake-Mirakl test harness. 447 backend tests. Telegram wired (bot, group `-5262705193`, webhook). Deployed gated off; a `test-run` produced a real order-aware Dutch reply as an Approve card.

### §F.2 — Durable lessons
- Mirakl message API requires multipart/form-data, not JSON — cost 1233 failed auto-sends before discovery.
- 92% of initially collected threads were Omiximo's own outbound invoice emails — filter by message direction at ingestion.
- SLA auto-escalation that hides threads from the inbox is worse than no SLA monitoring.
- "ESCALATED" == "PENDING_REVIEW" when everything needs human approval — one status.
- Jinja2 StrictUndefined + missing defaults = silent failures — include all template vars.
- HTML email content in Mirakl threads must be stripped before LLM calls.
- Never hide UI columns because "only one value exists" — multi-marketplace product.
- Collector must use Mirakl's `date_created`, not `datetime.now()`.
- Don't present A/B/C menus — pick the best option and do it; the user wants autonomous execution.
- **A per-event INSERT with no retention + autovacuum that never runs will silently reach tens of millions of rows / 18GB.** The `message_filtered` audit writer + an unvacuumed insert-only table did exactly this. Add retention/partitioning to any high-frequency log table; check `last_autovacuum`.
- **Never run a dev server (Vite `npm run dev`, `uvicorn --reload`) in a container in prod** — they hold the module graph + watcher in memory and OOM-loop. Multi-stage build → static/nginx or a single non-reload process.
- **The deployed image silently drifted from source** (a Next frontend image still running while the repo had migrated to Vite). Rebuild from `main` on every deploy; don't trust a long-lived `:tag`.
- **A FastAPI app with in-process background loops cannot be horizontally scaled** without double-running those loops (double-poll, double-send). Pin `replicas: 1` + `Recreate`, or extract the scheduler. (D-016)
- **Telegram bots ignore plain group messages under privacy mode**, and disabling privacy in @BotFather only takes effect after the bot is re-added (or promoted to admin). `/start@botname` (a command) is delivered regardless. Group chat ids are negative.
- The agent's LLM was real and working the whole time — the generic replies came from a prompt that forbade resolving anything + no real order data, not a missing/broken model. Fix the prompt + give it tools, don't replace the model.
- The `omiximo-env` secret has no Mirakl creds — the live Mirakl key lives per-account in `marketplace_accounts.api_key_encrypted` (Fernet), used by the legacy path.

---

## §G — Retrieval

### §G.1 — Section extract
```bash
sed -n '/^## §A/,/^## §B/p' PROJECT.md    # architecture (incl. deployment + agent)
sed -n '/^## §B/,/^## §C/p' PROJECT.md    # decisions
sed -n '/^## §C/,/^## §D/p' PROJECT.md    # roadmap + OQs
sed -n '/^## §D/,/^## §E/p' PROJECT.md    # database schema
sed -n '/^## §E/,/^## §F/p' PROJECT.md    # handoff (YAML hot state)
sed -n '/^## §F/,/^## §G/p' PROJECT.md    # history
sed -n '/^## §G/,$p'        PROJECT.md    # retrieval
```

### §G.2 — Codebase map / key paths
- `backend/app/services/agent/` — runner.py (loop), tools.py (tool registry + gate), fake_mirakl.py (test fixtures)
- `backend/app/services/telegram.py` — Telegram client; `backend/app/api/telegram.py` — Approve/Deny webhook; `backend/app/api/agent.py` — test-run
- `backend/app/services/draft_pipeline.py` — `AGENT_ENABLED` branch; `backend/app/services/collector.py` — new-thread Telegram activity
- `backend/app/models/agent_action.py`, `agent_event.py`; `backend/alembic/versions/011_agent_actions_events.py`
- `k8s/` — manifests + README runbook; `backend/scripts/prune_audit_log.sql` — audit cleanup
- `docs/superpowers/plans/2026-06-23-agent-loop-telegram.md` — the Phase 1 implementation plan

### §G.3 — Decision lookup
```bash
grep -n "^### .*D-[0-9]" PROJECT.md
```

### §G.4 — CLI quick reference (k3s on the `myvm` host, over SSH)
```bash
# tests (backend venv on the VM)
cd ~/omiximo-support/backend && . .venv/bin/activate && python -m pytest -q
# build + deploy the api image (runs alembic 011 in an init container)
cd ~/omiximo-support && docker build -t omiximo-api:prod backend \
  && docker save omiximo-api:prod | sudo k3s ctr images import - \
  && kubectl rollout restart deploy/api -n omiximo-support
kubectl get pods -n omiximo-support
kubectl logs -n omiximo-support -l app=api -c api --tail=50
# DB shell
kubectl exec -n omiximo-support db-0 -- psql -U omiximo -d omiximo_support
# fire a test thread through the agent (AGENT_FAKE_MIRAKL must be true)
curl -s -X POST http://127.0.0.1:30800/api/v1/agent/test-run -H 'Content-Type: application/json' -d '{"scenario":"broken_item"}'
# toggle a flag in the secret (then rollout restart)
kubectl patch secret omiximo-env -n omiximo-support --type=merge -p '{"data":{"AGENT_ENABLED":"'$(printf true|base64 -w0)'"}}'
```

### §G.5 — External
- GitHub: `clubeedg-ship-it/omiximo-support`
- Frontend: https://support.abbamarkt.nl · API: https://api-support.abbamarkt.nl
- Host: Tailscale `oopuopu-cloud` (SSH alias `myvm`, user `adminuser`); k3s namespace `omiximo-support`
- Telegram: bot `@omiximo_support_bot`, activity channel "Omiximo Support Activity Channel" (chat `-5262705193`), webhook `https://api-support.abbamarkt.nl/api/v1/telegram/webhook`
- LLM: OpenRouter (`https://openrouter.ai/api/v1`)
