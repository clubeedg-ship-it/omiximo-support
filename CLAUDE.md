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
- `safety_rules` = hard-coded invariants that block dangerous auto-replies (refund promises, external links, etc.)
- `knowledge_entry` = company policy/FAQ/product info stored in DB, retrieved for LLM-augmented drafting
- `smart_draft` = LLM-generated draft using knowledge + historical examples (ORANGE cases only) — the legacy, AGENT_ENABLED=False path
- `template_draft` = slot-filled Jinja2 template response (GREEN cases, or reference for ORANGE)
- `message_filter` = ingestion-time filter that rejects outbound/system noise (invoice emails, Zoho notifications)
- `operator_required` = boolean flag on threads forwarded by marketplace operators (MediaMarkt, Boulanger)
- `agent` = the autonomous tool-calling support agent (`services/agent/`): pulls real order data via tools, writes the resolution itself as the rep, proposes ONE action gated by Telegram. Replaces template-first drafting when `AGENT_ENABLED=True`.
- `agent_action` = a proposed agent action (`send_reply`/`escalate`) persisted as `proposed`, awaiting human Approve/Deny — the permission gate.
- `agent_event` = per-thread agent activity / tool-call timeline (its own table, kept out of `audit_log`).
- `activity channel` = the Telegram group (bot `@omiximo_support_bot` → "Omiximo Support Activity Channel", chat `-5262705193`) where new-thread notices, tool-call narration, and Approve/Deny cards land.
- `AGENT_FAKE_MIRAKL` = test/polish mode: read tools return fake order fixtures (real format), sends are simulated; powers `POST /api/v1/agent/test-run`.

## 4. Invariants
- The autonomous agent NEVER sends, refunds, or acts without a human Approve in Telegram — every agent action is an `agent_actions` row executed only by the Approve/Deny webhook. `AGENT_ENABLED` defaults False (legacy template path runs unchanged when off).
- ALL replies require human approval before sending (`AUTO_SEND_ENABLED=False`); threads NEVER auto-escalate or disappear (`SLA_AUTO_ESCALATE_ENABLED=False`).
- The API runs as a SINGLE process / k8s `replicas: 1` + `Recreate`: `app.main:app` starts in-process loops (mirakl_poller, auto_send_executor, sla_monitor). A second replica double-polls and double-sends — do not scale until the schedulers are extracted into their own worker.
- Deploy is **k3s** (namespace `omiximo-support`), NOT docker-compose. Containers run production builds — no `uvicorn --reload`, no Vite dev server (it OOM-looped). Postgres is a StatefulSet on a PVC (local-path), never a hostPath.
- Service NodePorts are pinned — api `30800`, frontend `30173` — because host nginx proxies the public domains to them. Never change them.
- Secrets (Telegram token, DB creds, LLM key, Fernet key) live in the `omiximo-env` / `omiximo-db` k8s secrets — never in git; `k8s/secret.example.yaml` holds placeholders only.
- Safety rules block dangerous content in drafts but never hide the draft from the reviewer.
- Every pipeline/agent decision gets an `audit_log` row; Mirakl API keys are Fernet-encrypted at rest.
- The message filter blocks outbound/system noise at ingestion — not retroactively; it does NOT write an audit row per filtered message (that bug grew `audit_log` to 43M rows / 18GB).
- HTML is stripped before LLM calls and in UI previews (`text_clean.py`, `stripHtml` util).

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
commit: 5afc581
state: >
  Telegram operator console (D-018) + Phase 2 Mirakl connectors (D-019) BUILT,
  DEPLOYED to k3s, verified live. 487 backend tests pass (all TDD), migration 012
  applied to the live DB. Agent gated off (AGENT_ENABLED=False), AGENT_FAKE_MIRAKL=
  true. Console: dossier card (cards.py) + threaded history; router webhook; ✏️ Edit
  (force-reply → re-render, telegram_sessions + context_json); 🌐 Translate (lang
  picker → MessageInsightService.translate_to); /pending /thread /stats /help /status.
  Phase 2: fetch_order 410 fixed (→ list endpoint); order/tracking/invoice facts all
  from the Mirakl order (connectors/mirakl.py extractors), verified against real data.
  Live fixes this session: webhook allowed_updates → [message,callback_query]
  (scripts/set_webhook.py); translate_to JSON-unwrap.
next: >
  ONE decision left — real go-live: set AGENT_ENABLED=true + AGENT_FAKE_MIRAKL=false
  (update omiximo-env secret + restart api) so the agent drafts REAL threads as
  approval cards (still human-gated). Decide backlog: ~23 unclassified vs new-only.
  Then Phase 2 remainder: approve_return/issue_refund actions; invoice PDF via Mirakl
  documents endpoint. Optional: edit escalation reasons, multi-operator claim-lock,
  webhook auto-register on startup.
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
