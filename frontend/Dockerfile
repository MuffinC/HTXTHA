# Frontend image: build the Vite app with Node 24, then serve only the static
# files with nginx (non-root, port 8080). The final image has no Node, no
# node_modules and no source (DECISIONS D-052).

# ---- build stage --------------------------------------------------------------
FROM node:24.22.3-bookworm-slim AS build
WORKDIR /app

# Dependencies first, so this layer is cached until the lockfile changes.
# npm 11 honours "allowScripts" in package.json (only esbuild's install script runs).
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ---- serve stage --------------------------------------------------------------
# nginx-unprivileged runs as uid 101 and listens on 8080 (no root, no port 80).
FROM nginxinc/nginx-unprivileged:1.31.7-alpine

# Rendered at start-up by the image's entrypoint (envsubst): the backend URL and
# the request-size limit come from the environment (see docker-compose files).
ENV BACKEND_URL=http://backend:8000 \
    NGINX_CLIENT_MAX_BODY_SIZE=260m
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"]
