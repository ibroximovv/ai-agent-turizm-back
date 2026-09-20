# Base Image
FROM oven/bun:1-alpine AS base
WORKDIR /app

# Dependencies Stage
FROM base AS dependencies
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Build Stage
FROM base AS build
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN bun run build

# Production Runner Stage
FROM base AS runner
ENV NODE_ENV=production

COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/package.json ./package.json

EXPOSE 3000

CMD ["bun", "dist/main.js"]
