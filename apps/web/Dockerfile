FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files from apps/web (build context is repo root)
COPY apps/web/package*.json ./
RUN npm install

# Copy source and build
COPY apps/web/ .
RUN npm run build

# Production stage - serve the static build
FROM node:22-alpine

WORKDIR /app
RUN npm install -g serve
COPY --from=builder /app/dist ./dist

EXPOSE 3000
CMD sh -c "serve dist --single -l ${PORT:-3000}"
