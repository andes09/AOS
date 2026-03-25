FROM node:22-alpine AS builder

WORKDIR /app

# Build context is apps/web (Railway Root Directory = apps/web)
COPY package.json .npmrc ./
RUN npm install

COPY . .
RUN npm run build

# Production stage — nginx for static serving
FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf.template /tmp/nginx.conf.template
COPY --from=builder /app/dist /usr/share/nginx/html

# Explicitly substitute only $PORT (with fallback to 3000), then start nginx.
# Avoids relying on the nginx entrypoint's template magic which silently drops
# variables that aren't set in the environment.
CMD ["/bin/sh", "-c", "export PORT=${PORT:-3000} && envsubst '$PORT' < /tmp/nginx.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
