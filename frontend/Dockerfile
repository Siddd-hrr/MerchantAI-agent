# Multi-stage production build for the merchant dashboard.
# VITE_* args are public API base URLs only — never pass secrets here.

FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

ARG VITE_AUTH_SERVICE_URL=http://localhost:8006
ARG VITE_ADMIN_SERVICE_URL=http://localhost:8003
ARG VITE_GATEWAY_URL=http://localhost:8000
ARG VITE_PAYMENT_LOG_SERVICE_URL=http://localhost:8008

ENV VITE_AUTH_SERVICE_URL=$VITE_AUTH_SERVICE_URL \
    VITE_ADMIN_SERVICE_URL=$VITE_ADMIN_SERVICE_URL \
    VITE_GATEWAY_URL=$VITE_GATEWAY_URL \
    VITE_PAYMENT_LOG_SERVICE_URL=$VITE_PAYMENT_LOG_SERVICE_URL

RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -q -O - http://127.0.0.1/ || exit 1
