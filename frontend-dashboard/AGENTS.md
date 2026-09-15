<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

# This app ships a LIVE chatbot — keep its knowledge in sync

frontend-dashboard mounts an explainer chatbot (`components/chatbot/chat-widget.tsx`)
whose entire brain is the repo-root `chatbot/` folder. It is live for clients, so
its knowledge MUST stay relevant to whatever this app currently shows. After you
**add, remove, or change any user-facing feature or page here, you MUST review and
update the chatbot knowledge in the same change** — never leave it stale.

Checklist (see `chatbot/README.md` and root `CLAUDE.md` §10 for the full contract):

- **Add / remove / rename a page (route):**
  1. `chatbot/manifest.json` — add/remove the `page → [packs]` entry (the page key
     is the route segment, e.g. `/patients` → `"patients"`).
  2. `chatbot/knowledge/<page>.md` — add/remove the pack (every pack on disk must
     be referenced by the manifest, or the test flags it as an orphan).
  3. `chatbot/knowledge/common.md` — update the "Halaman yang tersedia" list and
     the page count so the bot never miscounts the menu.
  4. Wire the integration so the new page key is accepted end-to-end (it is a
     strict enum in THREE places — keep them in sync):
     - `lib/api/chatbot.ts` — `ChatPage` type + the `page` `z.enum`.
     - `backend/app/api/routes/chatbot.py` — the `page: Literal[...]`.
     - `chat-widget.tsx` — `pageFromPath()` mapping + a `STARTERS` entry.
- **Change feature behavior, labels, thresholds, or copy:** update the relevant
  pack(s) so claims stay true. If you touched a chatbot-PINNED source
  (`chatbot/knowledge.lock.json` lists them), re-bless:
  `cd backend && python scripts/bless_chatbot_knowledge.py`.
- **Always verify:** `cd backend && pytest tests/test_chatbot_knowledge.py` must
  pass (manifest resolves, no orphan packs, hash lock, byte-identical label greps),
  plus `npm run typecheck` here.

Authoring rules for packs are binding (Indonesian, extraction-only/"the code wins",
**no PII ever**) — see `chatbot/README.md`.
