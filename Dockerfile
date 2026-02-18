FROM python:3.11-slim

WORKDIR /app

# System deps: build-essential for compiling numpy/pandas, gosu for entrypoint
RUN apt-get update && apt-get install -y --no-install-recommends build-essential gosu \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Non-root user (for collectstatic)
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

COPY --chown=app:app . .

RUN mkdir -p staticfiles data tmp && chown -R app:app staticfiles data tmp

ENV TMPDIR=/app/tmp
ENV GUNICORN_BIND=0.0.0.0:8000
EXPOSE 8000

COPY deploy/entrypoint.sh /app/deploy/entrypoint.sh
RUN chmod +x /app/deploy/entrypoint.sh

# Entrypoint runs as root (chown volumes, then run gunicorn as root)
ENTRYPOINT ["/app/deploy/entrypoint.sh"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/')" || exit 1

CMD ["gunicorn", \
    "--workers", "1", \
    "--threads", "1", \
    "--worker-tmp-dir", "/app/tmp", \
    "--bind", "0.0.0.0:8000", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "--capture-output", \
    "fuel_route.wsgi:application"]
