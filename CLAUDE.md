# omiximo-support — agent memory (always loaded)

Short snapshot + rules. Long-form lives in `PROJECT.md` — retrieve by section anchor.

## 1. Identity
- Project: `omiximo-support` (Mirakl customer support automation for Omiximo B.V.)
- Repo: `~/omiximo-support` on the `myvm` host (Tailscale `oopuopu-cloud`, user `adminuser`) — work only here, over SSH
- GitHub: `clubeedg-ship-it/omiximo-support` (private)
- Live: `https://support.abbamarkt.nl` (frontend), `https://api-support.abbamarkt.nl` (API)
- Branch policy: direct commits to `main` (a push-time gitleaks hook blocks secrets)

## 2. Session start
Read `PROJECT.md §E` first (current handoff). Then `§A` only if architectural, `§D` for schema.

Retrieve a section: `sed -n '/^## §E/,/^## §F/p' PROJECT.md`

## 3. Vocabulary
- `thread` = a Mirakl customer support conversation (one order, one or more messages)
- `risk_level` = GREEN/ORANGE/RED — classifier output determining draft strategy
- `safety_rules` = content checks (R1 refund promise, R2 return approval, R3 operator auto-reply, R4 unverified delivery, R5 warranty rejection, R6 external routing). On the agent path they are **WARN-ONLY** (see §4).
- `knowledge_entry` = company policy/FAQ/product info stored in DB, retrieved for LLM-augmented drafting
- `template_draft` / `smart_draft` = the legacy Jinja2-template + LLM draft path. Runs only when `AGENT_ENABLED=False`; superseded in production by the agent.
- `message_filter` = ingestion-time filter that rejects outbound/system noise (invoice emails, Zoho notifications)
- `operator_required` = flag on threads from the marketplace operator (MediaMarkt/Saturn, Boulanger). The agent SKIPS these — no card; handled in the web UI.
- `agent` = the autonomous tool-calling support agent (`services/agent/`): pulls real order data via Mirakl tools, writes the reply itself as the rep, proposes ONE action gated by Telegram. **LIVE in production** (`AGENT_ENABLED=True`, `AGENT_FAKE_MIRAKL=false`) on real customer threads.
- `agent_action` = a proposed agent action (`send_reply`/`escalate`) persisted as `proposed`, awaiting human Approve/Deny — the permission gate. `context_json` snapshots the gathered facts + safety violations so a card can be re-rendered (Edit/Translate).
- `agent_event` = per-thread agent activity / tool-call timeline (its own table, kept out of `audit_log`).
- `operator console` = the Telegram workflow (`api/telegram.py` router + `services/agent/cards.py`): ONE self-contained dossier card per proposed action — classification + order/tracking/knowledge facts + full threaded conversation history + the proposed reply/escalation — with buttons ✅ Approve / ❌ Deny / ✏️ Edit / 🌐 Translate (⤴️ Escalate / ❌ Dismiss for escalations), plus slash commands `/pending` `/thread <order>` `/stats` `/help` `/status`.
- `telegram_session` = transient "awaiting typed input" row (`telegram_sessions` table) backing the ✏️ Edit force-reply flow.
- `activity channel` = the Telegram group (bot `@omiximo_support_bot` → "Omiximo Support Activity Channel", chat `-5262705193`) where new-thread notices and approval cards land.
- `AGENT_FAKE_MIRAKL` = test mode: read tools return fake fixtures, sends simulated; powers `POST /api/v1/agent/test-run`. **False in production** (test-run returns 403) — post a test card via an in-pod script that sets it True in-process.

## 4. Invariants
- The autonomous agent NEVER sends, refunds, or acts without a human Approve in Telegram — every agent action is an `agent_actions` row executed only by the Approve/Deny webhook. **Production is LIVE: `AGENT_ENABLED=True`, `AGENT_FAKE_MIRAKL=false`** (config defaults are both False).
- ALL replies require human approval before sending (`AUTO_SEND_ENABLED=False`); threads NEVER auto-escalate or disappear (`SLA_AUTO_ESCALATE_ENABLED=False`).
- Safety on the agent path is **WARN-ONLY**: `safety_rules.validate` runs on every `send_reply`, the ⚠️ warning shows on the card + is stored in `context_json` + re-validates on Edit — but Approve is **NEVER withheld** (the operator decides; every reply is human-reviewed). Safety never hides the draft.
- The agent SKIPS (no card): `operator_required` threads (web UI handles them), `AWAITING_CUSTOMER`/`RESOLVED` threads (we already replied), and any thread that already has a `proposed` action (DEDUP). These guards prevent duplicate-looking card floods (root cause of the 2026-06-29 flood: ~70 operator threads each escalated into an identical card as the backlog drained).
- The Telegram webhook `allowed_updates` MUST include BOTH `message` and `callback_query`. `register_webhook()` sets this on startup; `scripts/set_webhook.py` is the manual tool. Missing `message` silently breaks ALL slash commands and the ✏️ Edit force-reply flow.
- Mirakl order fetch uses the OR11 LIST endpoint `GET /api/orders?order_ids=` — the single-id path `/api/orders/{id}` returns **410**. order/tracking/invoice facts all derive from that one order response (`connectors/mirakl.py`); no external carrier/invoicing APIs.
- The API runs as a SINGLE process / k8s `replicas: 1` + `Recreate`: `app.main:app` starts in-process loops (mirakl_poller, auto_send_executor, sla_monitor). A second replica double-polls and double-sends — do not scale until the schedulers are extracted into their own worker.
- Deploy is **k3s** (namespace `omiximo-support`), NOT docker-compose. Containers run production builds — no `uvicorn --reload`, no Vite dev server (it OOM-looped). Postgres is a StatefulSet on a PVC (local-path), never a hostPath.
- Service NodePorts are pinned — api `30800`, frontend `30173` — because host nginx proxies the public domains to them. Never change them.
- Secrets (Telegram token, DB creds, LLM key, Fernet key) live in the `omiximo-env` / `omiximo-db` k8s secrets — never in git; flip flags with `kubectl patch secret omiximo-env` + rollout restart.
- Every pipeline/agent decision gets an `audit_log` row; Mirakl API keys are Fernet-encrypted at rest.
- The message filter blocks outbound/system noise at ingestion — not retroactively; it does NOT write an audit row per filtered message (that bug grew `audit_log` to 43M rows / 18GB).
- HTML is stripped before LLM calls + in UI previews (`text_clean.py`, `stripHtml`). 🌐 Translate renders the WHOLE card (labels + facts + conversation + reply) via `translate_html`, preserving HTML tags, with a plain-text fallback.
- `approve_return` / `issue_refund` agent actions are deliberately NOT built — financial + conflict with D-003; require explicit sign-off + a safety-rules reconciliation.

## 5. Execution rules
- ABSOLUTE code quality over speed. No hacks, no workarounds, no monkey patches.
- If a feature requires a hack to ship: STOP. Fix the underlying design or report honestly.
- Backwards compatibility is NOT important — break bad APIs rather than preserving them.
- One bounded task at a time. Direct commits to `main`.
- Do not create planning files outside CLAUDE.md, PROJECT.md, and `docs/superpowers/plans/`.
- After every change: run the backend test suite (`.venv` on the VM) and give a clear, honest report on anything fragile.

## 6. Current snapshot
> Hot state — overwritten at session close. YAML.
```yaml
branch: main
commit: 2c6bcf0
state: >
  FLOOD FIX (494 tests): the agent now (a) DEDUPS — never a 2nd card for a thread
  with a proposed action; (b) SKIPS operator_required threads silently (no card —
  handled in web UI); (c) skips AWAITING_CUSTOMER/RESOLVED. Cause of the flood: as
  the backlog drained, ~70 operator threads each produced an identical escalation
  card. 12 stray cards were button-stripped + denied. Agent re-enabled (live).
  Earlier post-go-live fixes still apply (493→494 tests): SAFETY GATING IS WARN-ONLY — the ⚠️ warning
  always shows but Approve is never withheld (operator decides; AUTO_SEND off).
  Operator threads ESCALATE (not a blocked draft); agent skips AWAITING_CUSTOMER/
  RESOLVED threads; 🌐 Translate renders the WHOLE card (labels+facts+content) in
  the target language with HTML preserved (translate_html, plain-text fallback).
  Below is the go-live baseline —
  LIVE (D-020): AGENT_ENABLED=true + AGENT_FAKE_MIRAKL=false on k3s — the agent
  drafts REAL customer threads as human-gated approval cards (AUTO_SEND_ENABLED=
  False; nothing sends without a tap). 492 backend tests pass (all TDD), migration
  012 applied. Built+deployed+live-verified: console (D-018: dossier card + threaded
  history, router webhook, ✏️ Edit, 🌐 Translate, /pending /thread /stats /help
  /status); Phase 2 Mirakl connectors (D-019: fetch_order 410→list-endpoint fix,
  order/tracking/invoice facts from the order); and SAFETY-GATING of agent replies
  (safety_rules run on every send_reply → ⚠️ block + Approve withheld + re-validate
  on edit + webhook approve-block). register_webhook() on startup keeps
  allowed_updates=[message,callback_query]. Live proof: real German draft posted for
  a real order; R3 operator_required correctly caught + flagged.
next: >
  System is live and self-running (poller → agent draft → safety → approval card →
  operator taps). Monitor first real cards. NOT built (need your sign-off — financial
  + conflicts with D-003): approve_return / issue_refund actions + safety reconcil.
  Optional refinements: skip drafting operator_required upfront; edit escalation
  reasons; multi-operator claim-lock; invoice PDF via Mirakl documents endpoint;
  backlog reprocessing of existing PENDING threads.
blockers: []
updated: 2026-06-28
```

## 7. Pointer table
| Anchor | Content | Cadence |
|--------|---------|---------|
| `§A` | Architecture (incl. deployment + agent) | PR-gated |
| `§B` | Decisions (D-001…) | append-only |
| `§C` | Roadmap & open questions | overwrite |
| `§D` | Database schema | overwrite |
| `§E` | Handoff (current next-step) | overwrite |
| `§F` | History | append-only |
| `§G` | Retrieval | overwrite |

## 8. Session close
Before ending a session:
1. Decision landed? → append to `PROJECT.md §B`
2. Durable lesson? → append to `PROJECT.md §F`
3. Next-step changed? → overwrite `PROJECT.md §E`
4. Update §6 snapshot above
