# Multi-stage build: builder installs deps, runtime runs Gunicorn
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.11-slim AS runtime

WORKDIR /app

# Non-root user
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

COPY --from=builder /root/.local /home/app/.local
ENV PATH="/home/app/.local/bin:$PATH"

COPY --chown=app:app . .

RUN mkdir -p staticfiles data && chown -R app:app staticfiles data

USER app

ENV GUNICORN_BIND=0.0.0.0:8000
EXPOSE 8000

COPY --chown=app:app deploy/entrypoint.sh /app/deploy/entrypoint.sh
USER root
RUN chmod +x /app/deploy/entrypoint.sh
USER app

ENTRYPOINT ["/app/deploy/entrypoint.sh"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/')" || exit 1

CMD ["gunicorn", \
    "--workers", "1", \
    "--threads", "1", \
    "--bind", "0.0.0.0:8000", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "--capture-output", \
    "fuel_route.wsgi:application"]
