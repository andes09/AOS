FROM node:22-alpine AS builder

WORKDIR /app

# Build context is apps/web (Railway Root Directory = apps/web)
COPY package.json .npmrc ./
RUN npm install

COPY . .

ARG VITE_CLERK_PUBLISHABLE_KEY
ARG VITE_API_URL
ENV VITE_CLERK_PUBLISHABLE_KEY=$VITE_CLERK_PUBLISHABLE_KEY
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# Production stage — nginx for static serving
FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf.template /tmp/nginx.conf.template
COPY start.sh /start.sh
RUN chmod +x /start.sh
COPY --from=builder /app/dist /usr/share/nginx/html

CMD ["/start.sh"]
