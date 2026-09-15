This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Local development (CKG frontend-dashboard)

This is the **external, read-only dashboard** (scope=`prod` admin pool), including the
floating explainer chatbot. To run it against a local backend:

1. **Set the API URL — required, or the browser blocks every API call:**

   ```bash
   cp .env.local.example .env.local   # NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
   ```

   Why it's required (and why `127.0.0.1`, not `localhost`):
   - **CSP** — `next.config.ts` adds `NEXT_PUBLIC_API_URL`'s origin to the CSP
     `connect-src`. Unset → `connect-src 'self'` → the browser blocks calls to the API
     on `:8000` (shows "Network Error" on login), even though the request itself is valid.
   - **IPv4** — uvicorn binds `127.0.0.1` (IPv4); macOS resolves `localhost` to `::1`
     (IPv6) first, where nothing listens, so `localhost:8000` fails. `127.0.0.1` forces IPv4.
   - Editing `.env.local` requires a **dev-server restart** — `next.config.ts` (which
     builds the CSP) is read once at startup.

2. **Start the dev server:**

   ```bash
   npm run dev      # http://localhost:3000 — keep `localhost` for the page so its
                    # Origin stays in the backend CORS allowlist
   ```

3. **The backend must be running and reachable** — from `backend/` with the venv active:

   ```bash
   uvicorn app.main:app --reload --port 8000
   curl http://127.0.0.1:8000/health      # -> {"status":"ok"}
   ```

4. **Log in with the prod-pool account** (`PROD_ADMIN_EMAIL` / `PROD_ADMIN_PASSWORD`
   from `backend/.env`) — not the internal `admin@…` account; the two pools are separate.

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
