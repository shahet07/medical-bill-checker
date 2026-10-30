# Medical Bill Checker: API + web UI in one process.
# Run exactly one container: background jobs and rate limits live in-process.

# 1. Build the Next.js frontend as static files.
FROM node:22-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN NEXT_TELEMETRY_DISABLED=1 npm run build

# 2. Python app, serving the API and the built frontend.
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 app

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /root/.cache

COPY --from=frontend /frontend/out /app/frontend

USER app
ENV PYTHONUNBUFFERED=1 \
    BILLCHECKER_FRONTEND_DIR=/app/frontend
EXPOSE 8000

# --proxy-headers: HTTPS is terminated by the reverse proxy in front.
CMD ["uvicorn", "--factory", "billchecker.api:app_from_env", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "1"]
