# omiximo-support — agent memory (always loaded)

Short snapshot + rules. Long-form lives in `PROJECT.md` — retrieve by section anchor.

## 1. Identity
- Project: `omiximo-support` (Mirakl customer support automation for Omiximo B.V.)
- GitHub: `clubeedg-ship-it/omiximo-support` (private)
- Live: `https://support.abbamarkt.nl` (frontend), `https://api-support.abbamarkt.nl` (API)
- Branch policy: `main` until first feature lands

## 2. Session start
Read `PROJECT.md §E` first (current handoff). Then `§A` only if architectural, `§D` for workstreams. 

Retrieve a section: `sed -n '/^## §E/,/^## §F/p' PROJECT.md`

## 3. Vocabulary
- `thread` = a Mirakl customer support conversation (one order, one or more messages)
- `risk_level` = GREEN/ORANGE/RED — classifier output determining draft strategy
- `safety_rules` = hard-coded invariants that block dangerous auto-replies (refund promises, external links, etc.)
- `knowledge_entry` = company policy/FAQ/product info stored in DB, retrieved for LLM-augmented drafting
- `smart_draft` = LLM-generated draft using knowledge + historical examples (ORANGE cases only)
- `template_draft` = slot-filled Jinja2 template response (GREEN cases, or reference for ORANGE)
- `message_filter` = ingestion-time filter that rejects outbound/system noise (invoice emails, Zoho notifications)
- `operator_required` = boolean flag on threads forwarded by marketplace operators (MediaMarkt, Boulanger)

## 4. Invariants
- ALL messages require human approval before sending (AUTO_SEND_ENABLED=False)
- Threads NEVER auto-escalate or disappear (SLA_AUTO_ESCALATE_ENABLED=False)
- Safety rules block dangerous content in drafts — but do not hide the draft from the reviewer
- Every action (classify, draft, approve, send, fail) gets an audit_log row
- Mirakl API keys are Fernet-encrypted at rest — never stored plaintext
- The message filter blocks outbound/system noise at ingestion — not retroactively
- GREEN templates only, LLM never generates freeform for GREEN (D1)
- Insight/translation is on-demand, never pipeline-blocking (D6)
- HTML is stripped before LLM calls and in UI previews (text_clean.py, stripHtml util)

## 5. Execution rules
- ABSOLUTE code quality over speed. No hacks, no workarounds, no monkey patches.
- If a feature requires a hack to ship: STOP. Fix the underlying design or report honestly.
- Backwards compatibility is NOT important — break bad APIs rather than preserving them.
- One bounded task at a time. Direct commits to `main`.
- Do not create planning files outside CLAUDE.md and PROJECT.md.
- After every change: clear, honest report on anything fragile.

## 6. Current snapshot
> Overwritten at session close.
- branch: `main`
- status: 404 backend tests pass, 43 frontend tests pass, 97 real threads in inbox
- last: workflow simplification — killed auto-send/SLA crons, single "Send Reply" button, cleaned DB noise
- next: configure Clerk auth (or keep dev-bypass for single-user), Mirakl Connect credentials for live polling

## 7. Pointer table
| Anchor | Content | Cadence |
|--------|---------|---------|
| `§A` | Architecture | PR-gated |
| `§B` | Decisions (D-001...) | append-only |
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
