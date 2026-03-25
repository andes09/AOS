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
COPY start.sh /start.sh
RUN chmod +x /start.sh
COPY --from=builder /app/dist /usr/share/nginx/html

CMD ["/start.sh"]
