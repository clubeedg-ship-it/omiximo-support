# Telegram Operator Console — design

Status: **draft for review** · 2026-06-28 · supersedes nothing (builds on
`2026-06-23-agent-loop-telegram.md` and the dossier card in
`app/services/agent/cards.py`).

## 1. Goal

Turn the Telegram activity channel from a stream of one-off messages into a
smooth, professional **operator console**: the place a human reviews what the
agent proposes, edits/translates it, walks the conversation history, navigates
threads, and checks system state — without leaving Telegram and without the
channel turning into noise.

Done already (increment 0): a self-contained **dossier card** per proposed
action (classification + customer quote + order/tracking/knowledge facts +
the proposed reply/escalation) with action-aware buttons, plus a live per-tool
narration ticker. This doc designs everything on top.

## 2. Principles (what makes it feel organised)

1. **One card per thread, edited in place.** The dossier card is the anchor.
   Buttons mutate *that* message (`editMessageText`) instead of posting new
   ones. The channel stays clean; scrollback stays meaningful.
2. **State-aware toolbar.** The buttons under a card depend on the action's
   state (proposed / editing / translated / decided). One renderer owns this.
3. **Slash commands are the global entry points.** `/pending`, `/thread`,
   `/stats`, `/status`, `/help`. Buttons act *within* a card; commands move
   *between* things.
4. **Force-reply captures typed input.** Editing a draft, adding an escalation
   note: the bot asks, the operator replies, the bot folds it back into the card.
5. **Acknowledge every tap.** `answerCallbackQuery` so the client spinner clears
   and the operator gets instant feedback ("Draft updated", "Translating…").
6. **Best-effort, never breaks the pipeline.** Every Telegram call already
   degrades to a no-op without a token and swallows network errors. Keep that.

## 3. Card state machine

An `AgentAction` drives one card. States and their toolbars:

| State | Trigger | Card body | Toolbar (reply) | Toolbar (escalate) |
|-------|---------|-----------|-----------------|--------------------|
| `proposed` | agent proposes | dossier (incl. conversation block) + draft/reason | `✅ Approve` `✏️ Edit` `🌐 Translate` | `⤴️ Escalate` `❌ Dismiss` |
| `editing` | tap `✏️ Edit` | dossier + "✍️ awaiting new text…" | `🔙 Cancel` | — |
| `picking-lang` | tap `🌐 Translate` | dossier + a row of language buttons | `🔙 Back` | — |
| `translated` | pick a language | dossier + draft + 🌐 ⟨lang⟩ view | `🔙 Back` `✅ Approve` `✏️ Edit` | — |
| `decided` | Approve/Deny/Escalate/Dismiss | dossier + status footer, **no buttons** | — | — |

Maps to existing `ActionStatus`: `PROPOSED → APPROVED/EXECUTED | DENIED | FAILED`.
`editing`/`picking-lang`/`translated` are *view* states (no status change); they
live as transient session state, not new `ActionStatus` values.

**Conversation block (always in the card).** The customer-context section
renders the full back-and-forth as **threaded quotes** — one labelled header
(`👤 Klant` / `🧑‍💼 Wij` · timestamp) above a native `<blockquote>` per turn,
newest marked `· nieuwste` — whenever the thread has >1 message; a single-message
thread shows that one turn. Long threads collapse older turns into one
`<blockquote expandable>` with the newest turn shown expanded, to stay within
Telegram's 4096-char limit. There is no separate "History" button — history is
the card.

## 4. Command set

| Command | Does | Notes |
|---------|------|-------|
| `/help` | button + command legend | static; first F1 smoke test |
| `/status` | poller alive?, last poll, pending count, `AGENT_ENABLED`/`AGENT_FAKE_MIRAKL` | read-only health |
| `/pending` | paginated list of threads awaiting review; tap → (re)post that thread's card | `◀ ▶` paging |
| `/thread <order_id>` | post the dossier card for a specific thread | reuses the renderer |
| `/stats` | today: received / sent / escalated / pending | read-only |

## 5. Increments

### F0.5 — Conversation block in the card *(build next)*

Pure card-builder work, independent of the router, high operator value, so it
goes first. `build_action_card` gains an optional `messages` argument (a list of
`ThreadMessage`-like turns: `author_type`, `author_name`, `body`, `created_at`,
`sequence_number`). `_propose_action` (`tools.py`) queries the thread's messages
(as `runner._build_messages` already does) and passes them in. Rendering:
threaded quotes per §3; `customer`→`👤 Klant`, everything else→`🧑‍💼 Wij`;
oldest turns collapse into one `<blockquote expandable>` past a turn/length
threshold. Falls back to the single `customer_message` quote when no messages are
supplied. Messages are persisted (`thread_messages`), so re-rendering always
re-queries — no snapshot needed for them. TDD against fabricated turn lists.

### F1 — Foundation: router + edit-in-place + state renderer

The backbone. Without it, every feature bolts onto the webhook messily.

- **Webhook → dispatcher.** `app/api/telegram.py` currently handles only
  `callback_query` with `approve:`/`deny:`. Refactor into a router that also
  handles (a) other callback prefixes (`edit:`, `tr:`, `hist:`, `page:`),
  (b) `message` updates carrying a `bot_command` entity (slash commands),
  (c) `message` updates that are force-reply replies to a bot prompt. A small
  registry maps prefix/command → handler. Keep the secret-token check.
- **Telegram service additions** (`app/services/telegram.py`):
  `edit_message(message_id, text, reply_markup)` → `editMessageText`;
  `answer_callback(callback_id, text="")` → `answerCallbackQuery`;
  `prompt_reply(text)` → `sendMessage` with `force_reply` markup. All best-effort.
- **State-aware renderer** (`app/services/agent/cards.py`): a
  `render_card(action, thread, facts, *, state) -> (text, reply_markup)` that
  owns body + toolbar per state. `build_action_card` becomes its `proposed`/
  `decided` body. `button_labels` folds into the toolbar builder.
- **First commands:** `/help`, `/status` — exercise the router end to end.
- **Acks:** `answerCallbackQuery` on every tap so the client spinner clears.

*Built lean (no migration): `context_json` on `AgentAction` + the
`telegram_sessions` table (migration 012) and the state-aware renderer/toolbar
are **deferred to F2/F3**, where Edit/Translate first need to re-render a card
after the run. Decided cards still strip buttons + post a reply note as before.*

### F2 — Edit draft (`✏️`)

Tap `✏️ Edit` → `answerCallbackQuery` + `prompt_reply("Reply with the new
message…")` and mark the action `editing` (store the prompt message_id on a
session record). Operator's force-reply arrives as a `message` update; the
router matches it to the awaiting action, updates `payload_json["body"]`,
re-renders the card to `proposed` with an "✏️ edited by <user>" line, and clears
the editing state. `🔙 Cancel` aborts. Audit each edit.

### F3 — Translate (`🌐`) — webUI parity

Reuse `MessageInsightService` (two-step translate-then-verify, mock mode,
never raises). **Parity nuance:** the existing `translate_draft` goes
*English → customer language* (for the human-writes-in-English flow). The agent
already drafts in the customer's language, so the *useful* Telegram direction is
*customer language → English* so a non-Dutch reviewer can verify both the
customer quote and the draft. This needs a translate-to-English path (the
existing endpoint rejects English targets). **Open question (Q3).** UI: `🌐`
toggles a `translated` view showing the English rendering beneath the originals;
`🔙 Back` returns. Translation is display-only — the *sent* reply stays in the
customer's language. **UI:** `🌐 Translate` enters `picking-lang` (a row of
language buttons: NL · EN · FR · DE …); picking one renders the `translated`
view beneath the originals; `🔙 Back` returns. Target is operator-chosen, not
fixed (decision Q3).

### F4 — Cross-thread navigation (`/pending`, `/thread`)

In-thread history now lives in the card (F0.5), so F4 is just moving *between*
threads. `/pending` lists threads awaiting review with `◀ ▶` paging; tapping one
re-posts its dossier card. `/thread <order_id>` jumps directly to one.

### F5 — System commands & polish

`/stats`, richer `/status`, `/help` legend kept in sync, consistent emoji/labels
pass across all cards.

## 6. Testing

Per-unit TDD as established: pure renderer/toolbar functions tested without I/O
(like `test_agent_cards.py`); the router tested with fake update payloads +
a fake Telegram (capture `edit_message`/`answer_callback` calls) and the SQLite
test DB; translation tested in mock mode. Backend suite (`.venv` on VM) green
after each increment. No real sends in tests (no token → no-op).

## 7. Deploy

Deploy per increment once green (k3s, **Recreate, replicas: 1** — never bump
replicas / RollingUpdate: in-process schedulers double-send, D-016). The
dossier card (increment 0) batches with F1's first deploy. NodePorts
30800/30173 unchanged; Postgres stays on the PVC.

## 8. Sequencing

`0 (done)` → **F0.5 (conversation block — done)** → **F1 (router + `/help`,
`/status` + answerCallbackQuery — done)** → F2 (Edit; brings migration 012 +
state renderer/toolbar + edit_card/prompt_reply) → F3 (Translate, language
picker) → F4 (cross-thread nav) → F5 (system cmds). The dossier card
(increment 0) + F0.5 + F1 batch into the first deploy. Revisit the
`AGENT_ENABLED` go-live once the console feels comfortable to operate.

## 9. Decisions (resolved)

- **D1 — Edit-session state:** a small **`telegram_sessions`** table
  (chat + prompt message_id → action_id + kind), so awaiting-input state
  survives restarts. (migration 012, alongside `AgentAction.context_json`.)
- **D2 — Multi-operator:** **first-tap-wins** as today; a "🔒 claimed by X"
  lock can come later.
- **D3 — Translate:** **language picker** (modal row of language buttons);
  translation is display-only, the sent reply stays in the customer's language.
- **D4 — History:** **always folded into the card** as threaded quotes when a
  thread has >1 message (F0.5) — no separate History button.
```
