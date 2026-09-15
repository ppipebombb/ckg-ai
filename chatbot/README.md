# chatbot/ — knowledge base for the frontend-dashboard explainer chatbot

This folder is the **entire mind** of the floating chatbot on frontend-dashboard.
The bot answers ONLY from these files — no RAG, no memory, no patient data.
See `CHATBOT_BUILD_PROMPT.md` (repo root) for the full feature spec; the
backend/frontend integration reads this folder at runtime.

## Layout

| File | Role |
|---|---|
| `system.md` | Guardrail system prompt (Indonesian). Composed first. |
| `manifest.json` | `page → [knowledge packs]` mapping. Frontend sends the route segment as `page`; backend concatenates the listed packs after `system.md`. Unknown page → `common`. |
| `knowledge/common.md` | App-level truth: the two sources (ePus/ASIK), scrape → merge lineage, "CKG patient" definition, 30h cache + 5am warm, how to fix wrong data, what the bot cannot answer. |
| `knowledge/dashboard.md` | What every `/dashboard` card counts and the exact rule behind each number (HT summary, DM TW tally, totals card), incl. why Card-1 total ≠ registry total. |
| `knowledge/registri-hipertensi.md` | Full kertas-kerja logic: syarat, riwayat sources, TD1/TD2/rerata, KMK 84/2026 bands, follow-up labels (byte-identical to code), obat families, FAQ, Dasar aturan. |
| `knowledge/registri-diabetes-melitus.md` | Same shape for the DM kertas kerja: syarat, riwayat sources, GDS/GDS 2/GDP/GD2PP/HbA1C, diagnosis + prediabetes bands, the N15 validity rule, U17 follow-up labels (byte-identical to code), obat families, Dasar aturan. |
| `knowledge.lock.json` | Drift guard: sha256 of every **pinned source file** these packs were verified against. |

## Authoring rules (binding)

1. **Extraction only — the code always wins.** Every threshold, label string,
   and rule must be traceable to the pinned source files (or the user-facing
   formula card / `documents/KERTAS_KERJA_HIPERTENSI_LOGIC.md`, which is
   local-only/gitignored — these packs are its shipped distillation). Never
   write a rule from general/medical knowledge.
2. Packs are **Indonesian**, plain markdown, written for non-technical
   puskesmas/dinas staff. Reuse the FAQ wording — it is client-tested.
3. The follow-up labels and the band thresholds must appear **byte-identical**
   to the constants in `backend/app/services/hipertensi_registry_scan.py`,
   `backend/app/services/dm_registry_scan.py` and
   `backend/app/services/lipid_registry_scan.py` (one test per registry pack).
   The Dislipidemia test additionally asserts the three ways that registry
   DIVERGES from its siblings (measurement-only syarat, riwayat reported but not
   filtered on, **quarterly** control months) — a reader who carries the DM rules
   over gets all three wrong, so the pack must state them, not merely omit the
   DM wording.
4. The bot and the on-screen "Cara Membaca Kertas Kerja Ini" card must never
   contradict each other.
5. Keep total knowledge ≤ ~25 KB. If it grows past that, tighten prose — do
   not build retrieval machinery.
6. **No PII, ever.** No patient names, NIKs, or row data in any pack. (One
   anonymized numeric example like "137/100" is fine.)

## How knowledge stays up to date (the autonomy contract)

Knowledge ships **with the code**: `backend/Dockerfile` copies this folder
into the image, so every `git pull` + rebuild updates the bot automatically.
Freshness is then enforced, not remembered:

- `chatbot/knowledge.lock.json` pins the sha256 of every source file the packs
  were verified against (the hipertensi + DM registry scans, report routes,
  dashboard scan/cards, the formula cards, the described pages). Hashes are
  taken over LF-normalized bytes, so a Windows (`core.autocrlf`) checkout and a
  Linux/CI one agree — see `sha256_normalized` in the bless script.
- `backend/tests/test_chatbot_knowledge.py` fails when any pinned file's hash
  no longer matches the lock — i.e. **someone changed user-visible logic
  without re-checking the bot's knowledge** — and also greps the packs for the
  byte-identical label constants and thresholds.
- The fix-flow after changing a pinned source:
  1. Re-read the affected pack(s); update any claim that changed (often
     nothing — a refactor changes the hash but not the behavior).
  2. Re-bless: `cd backend && python scripts/bless_chatbot_knowledge.py`
  3. `pytest tests/test_chatbot_knowledge.py` → green. Commit pack + lock in
     the same PR as the logic change.

This is deliberate friction: a one-command re-bless forces a 30-second "did my
change affect what the bot tells users?" review on exactly the files that
feed user-visible numbers. CLAUDE.md §10 makes this part of the standing
project rules, so agent-driven changes follow it without being asked.

## Updating in production without a rebuild (optional)

`docker compose` can bind-mount `./chatbot:/app/chatbot` over the baked copy
to hot-patch knowledge between releases. The default (baked into the image) is
the safe path — versioned, reviewed, atomic with the code it describes.

---

# Runtime architecture (how the integration works)

The sections above are the **content contract** (what goes in the packs). This
section is the **integration reference** (how the running app uses them). The
single load-bearing property: **the LLM request contains zero patient data** —
only our versioned markdown, the user's question, and a capped history. A
successful prompt injection can therefore make the bot *wrong*, never make it
*leak*. Do not weaken this.

## Where the runtime code lives

| Concern | File |
|---|---|
| Floating chat UI ("Asisten CKG") | `frontend-dashboard/components/chatbot/chat-widget.tsx` |
| Mount point (inside the auth-gated dashboard) | `frontend-dashboard/app/(dashboard)/layout.tsx` |
| Frontend API client + zod types | `frontend-dashboard/lib/api/chatbot.ts` |
| Backend route `POST /chatbot/messages` | `backend/app/api/routes/chatbot.py` |
| Knowledge loader (`build_system_prompt`) | `backend/app/services/chatbot_knowledge.py` |
| LLM call (`chat_complete`) | `backend/app/integrations/llm_chat.py` |
| Per-admin rate limit | `backend/app/core/rate_limit.py` |
| Drift lock + bless + test | `chatbot/knowledge.lock.json`, `backend/scripts/bless_chatbot_knowledge.py`, `backend/tests/test_chatbot_knowledge.py` |

## Request flow

1. **UI** — the widget lives in the `(dashboard)` route group, which is wrapped
   in `<RequireAuth>`. It never renders on `/login` and never for a logged-out
   user. Input is capped at **1000 chars**; the send button is disabled when
   empty.
2. **History assembly (client)** — `send()` in `chat-widget.tsx` walks the
   visible bubbles and keeps **only completed user→assistant pairs**, dropping
   any errored turn so roles stay strictly alternating (two `user` messages in a
   row breaks some OpenAI-compat gateways). Each kept message is clamped to 2000
   chars; it then sends the **last 20 items** (`history.slice(-20)`).
3. **POST `/chatbot/messages`** — plain JSON request/response (**no SSE/streaming
   for the chatbot**), through the single axios instance which attaches
   `Authorization: Bearer <token>`. Body = `{ message, page, history }`.
4. **Backend** (`chatbot.py`): rate-limit → load active config → build system
   prompt from packs → call the LLM → log usage (no content) → return
   `{ answer }`.

## How the prompt is built (the only thing the model ever sees)

`build_system_prompt(page)` (`chatbot_knowledge.py`) composes
`system.md` + `"\n\n# BASIS PENGETAHUAN\n"` + the packs `manifest.json` maps to
`page` (unknown page → `common`). The route then assembles the final message
array — and this is the **complete** set of content sent to the model:

```
[ system    : system.md  +  knowledge packs for this page,
  ...        : last 20 history items (10 user/assistant pairs),
  user       : the current question ]
```

No DB, no RAG, no retrieval, no patient rows. Files are cached in-process by
path+mtime, so steady state does no disk IO but a bind-mounted hot-patch is
picked up on next read.

## Gates & security (five independent gates)

1. **Auth** — endpoint requires a valid bearer token via `get_dashboard_admin_id`.
   The UI is also behind `<RequireAuth>`, and a 401 clears auth and redirects to
   login.
2. **Scope allowlist** — `get_dashboard_admin_id` accepts **both** internal and
   `prod`-scope admins. frontend-dashboard (prod scope) is *default-deny* on
   every write/mutation endpoint; the chatbot is a **deliberate** exception,
   flagged as such in a comment at the dependency.
3. **Rate limit** — `enforce_chatbot_rate_limit(admin_id)`: **10 requests per
   admin per 60 s**, Redis fixed-window. Over-limit → `429` with `Retry-After`;
   the message surfaces verbatim in the chat bubble.
4. **Feature flag** — only the `LlmConfig` row with `is_active_chatbot=True` is
   used. None set → feature is **off by default** → `503 "Chatbot belum
   dikonfigurasi"`. No silent fallback to a generic LLM config.
5. **Fail-loud on broken deploy** — a missing pack / knowledge folder raises
   `ChatbotKnowledgeUnavailable` → `503`, never an answer from an empty brain.

**Other limits & hygiene:** output capped at `_MAX_TOKENS = 1800`;
`reasoning_effort = cfg.reasoning_effort or "high"` with `thinking=True` (factual,
low-hallucination); temperature 0 (0.01 for riset.ai); API key is Fernet-encrypted
and decrypted per request; every call is logged to `llm_logs` with
`source="chatbot"` (tokens, cost, latency) — **never the message content**; on
error only `str(exc)[:2000]` is stored.

## Conversation history window (the "auto-compact")

There is **no summarization and no server-side session**. "Compaction" is a
single **fixed sliding window of the last 20 messages = 10 user/assistant
pairs**, enforced in two places so a forged client can't exceed it (the two
caps MUST stay in sync):

- **Client** — `history.slice(-20)` in `chat-widget.tsx`.
- **Server** — Pydantic `history: ... max_length=20` *and* `body.history[-20:]`
  when assembling the prompt (`chatbot.py`).

Messages older than the last 10 exchanges simply fall off — they are never
summarized or stored. Per-message caps: question ≤ 1000 chars, each stored
history item ≤ 2000 chars.

**Why hallucination is not prevented by "starting a new session":** the
conversation only lives in React `useState`, so it resets on page reload or when
you navigate out of `(dashboard)` (the widget unmounts) — but that is *not* the
anti-hallucination mechanism. The bot stays factual because (a) the model only
ever sees the curated packs (nothing to confuse or leak), (b) `system.md` forbids
guessing and states the knowledge base outranks chat history, and (c) the
hash-lock test keeps the packs byte-true to the code.

## In plain language (for relaying to non-engineers)

**The key idea: what's on screen ≠ what's sent to the AI.** The chat panel keeps
the *whole* conversation visible (you can scroll up to the first message forever
— nothing is ever deleted from the screen). But what we actually send to the
LLM on each request is a fixed, bounded payload — it can never grow without
limit, so the context cannot "bloat."

**What we send to the chat-completion API each request is three parts**, not
just the history:

1. **System prompt** — `system.md` + the knowledge packs for the current page.
   **Sent in full, every single request.** This is the bulk of the context and
   the part that keeps answers factual.
2. **Conversation memory** — the **last 20 messages = 10 user/assistant pairs**.
   This is the *only* part that "compacts."
3. **The user's brand-new question** (separate from the 20).

So the message list is `[system, …up to 20 history items, new question]` — at
most ~22 messages.

**Vocabulary:** a *message* is one bubble (a user line or a bot line). A *pair*
(turn/exchange) is one user message **+** one bot reply = 2 messages. So "20
messages" = "10 pairs" = the last 10 complete back-and-forths.

**It's a sliding window, not a delete.** Nothing is removed — the AI is simply
only ever given the *most recent* 20 items. As the chat grows past 10 pairs, the
oldest pair falls *outside* the window that gets sent (but stays on screen):

| User sends | Memory the AI receives | Still sees Q1? |
|---|---|---|
| Question 10 | Q1–Q9 + answers | ✅ |
| Question 11 | Q1–Q10 + answers (exactly 10 pairs) | ✅ |
| Question 12 | **Q2**–Q11 + answers (Q1 slid out) | ❌ |
| Question 13 | Q3–Q12 + answers | ❌ |

**The catch:** if a user, deep in a long chat, asks *"what did I ask you first?"*,
the bot can't recall it — that early message is outside the sent window. **But
this only affects "remember what we talked about" questions.** Factual answers
are unaffected, because the knowledge packs (part 1) are re-sent in full on
every request — "What does *dalam pengobatan* mean?" gets the same correct
answer whether it's the 1st question or the 50th.

**One-paragraph version to relay:** *The bot keeps the whole conversation on
screen, but it only feeds the AI your last 10 questions and answers (a rolling
"last 20 messages" window) plus the full knowledge packs and your new question.
Older messages stay visible but aren't sent, so it can't recall something from
very early in a long chat — yet factual answers are always correct, because the
facts are re-sent in full every time. It's bounded by design, so the context
can never bloat.*
