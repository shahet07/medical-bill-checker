# Medical Bill Checker: API + web UI in one process.
# Run exactly one container: background jobs and rate limits live in-process.
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 app

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && rm -rf /root/.cache

USER app
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# --proxy-headers: HTTPS is terminated by the reverse proxy in front.
CMD ["uvicorn", "--factory", "billchecker.api:app_from_env", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "1"]
