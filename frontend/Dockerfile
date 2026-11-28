# syntax=docker/dockerfile:1
FROM node:24.22.3-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:24.22.3-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# next.config is read at build time, so the internal API address is baked in here.
ARG API_INTERNAL_URL=http://api:8000
ENV API_INTERNAL_URL=$API_INTERNAL_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# PM2 for the runtime image only, from its own lockfile (pm2/), so the build is reproducible.
FROM node:24.22.3-alpine AS pm2
WORKDIR /opt/pm2
COPY pm2/package.json pm2/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM node:24.22.3-alpine AS runner
WORKDIR /app
# PM2_HOME in /tmp: PM2 keeps its socket and pid files there, outside the app directory.
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000 \
    WEB_RUNNER=pm2 \
    WEB_INSTANCES=2 \
    PM2_HOME=/tmp/.pm2 \
    PATH="/opt/pm2/node_modules/.bin:$PATH"
COPY --from=pm2 /opt/pm2/node_modules /opt/pm2/node_modules
ARG API_INTERNAL_URL=http://api:8000
ENV API_INTERNAL_URL=$API_INTERNAL_URL
# Owned by root, run as `node`: the server can read its files but never change them, even
# with READ_ONLY_FS=false (layer L4). It needs nothing writable outside /tmp.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
COPY --from=build /app/edge-headers.cjs /app/stream-shutdown.cjs /app/ecosystem.config.cjs /app/start.sh ./
USER node
EXPOSE 3000
# WEB_RUNNER=pm2 (PM2 cluster, WEB_INSTANCES workers) or node (one process): see start.sh.
CMD ["sh", "./start.sh"]
