# Frontend image: build the SPA, then serve it from nginx alongside an API reverse proxy.

# ---- build stage ----
# node:24 matches the Node the project is developed against. This stage carries the whole
# node_modules tree and is discarded - only the built assets reach the final image.
FROM node:24-slim AS build

WORKDIR /app

# npm ci, not npm install: installs exactly the pinned tree from package-lock.json and fails if
# the lockfile and package.json disagree, so a build can never silently resolve a new version.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines VITE_* variables at build time - they are not read at runtime - so the API base
# URL has to be known here. Defaults to the relative path /api, which is what makes the
# same-origin nginx proxy work without any per-environment configuration. Override at build
# time only if the API genuinely lives on another host.
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

# ---- runtime stage ----
FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Listens on 8080 rather than 80 so the server can run unprivileged - binding below port 1024
# requires root. nginx-alpine ships an 'nginx' user already.
RUN touch /var/run/nginx.pid \
    && chown -R nginx:nginx /var/run/nginx.pid /var/cache/nginx /usr/share/nginx/html
USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1
