# Static front end (no build step) served by nginx; /api is proxied to the backend.
FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY src/trader/web /usr/share/nginx/html/static
COPY src/trader/web/index.html /usr/share/nginx/html/index.html
COPY docs/screenshots /usr/share/nginx/html/screenshots
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD wget -qO- http://127.0.0.1/healthz || exit 1
