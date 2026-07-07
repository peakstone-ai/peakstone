# Peakstone website (Next.js). Build context = web/ (see infra/docker-compose.yml).
#
# The pages are fully server-rendered and fetch the API server-side, so NEXT_PUBLIC_API_URL points at
# the API container's INTERNAL address (http://api:8000) — the browser only ever receives HTML and
# never calls the API directly. External clients reach the API via the /api/* route Caddy exposes.

# --- build ------------------------------------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# baked into the server bundle at build time (Next inlines NEXT_PUBLIC_* at build).
# API_URL = server-side fetches (internal, never rendered); API_PUBLIC_URL = the address shown to
# visitors in curl examples etc. (compose derives it from PEAKSTONE_DOMAIN).
ARG NEXT_PUBLIC_API_URL=http://api:8000
ARG NEXT_PUBLIC_API_PUBLIC_URL=https://peakstone.ai/api
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_API_PUBLIC_URL=${NEXT_PUBLIC_API_PUBLIC_URL}
RUN npm run build

# --- run --------------------------------------------------------------------------------------
FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production HOSTNAME=0.0.0.0 PORT=3000
# the standalone output carries its own minimal node_modules + server.js; static/ and public/ are copied alongside
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
