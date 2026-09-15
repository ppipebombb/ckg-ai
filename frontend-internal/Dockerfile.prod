FROM node:22-alpine AS deps
WORKDIR /app
RUN npm install -g corepack@latest && corepack enable && corepack prepare pnpm@10.33.0 --activate
COPY frontend-internal/package.json frontend-internal/pnpm-lock.yaml frontend-internal/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS builder
WORKDIR /app
RUN npm install -g corepack@latest && corepack enable && corepack prepare pnpm@10.33.0 --activate
COPY --from=deps /app/node_modules ./node_modules
COPY frontend-internal/ ./
# Repo-root shared feature code; the build script syncs it into ./_shared
# (node ../frontend-shared/sync.mjs ./_shared). WORKDIR is /app, so ../frontend-shared = /frontend-shared.
COPY frontend-shared/ /frontend-shared/
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
RUN addgroup -S nodejs && adduser -S nextjs -G nodejs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
