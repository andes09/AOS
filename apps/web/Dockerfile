FROM node:22-alpine AS builder

WORKDIR /app

# Build context is apps/web (Railway Root Directory = apps/web)
COPY package.json .npmrc ./
RUN npm install

COPY . .
RUN npm run build

# Production stage - serve the static build
FROM node:22-alpine

WORKDIR /app
RUN npm install -g serve
COPY --from=builder /app/dist ./dist

EXPOSE 3000
CMD sh -c "serve dist --single -l ${PORT:-3000}"
