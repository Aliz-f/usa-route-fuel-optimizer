#!/bin/bash
set -e
# Fix volume permissions (named volumes are often root-owned on first run)
chown -R app:app /app/staticfiles /app/data /app/tmp 2>/dev/null || true
# Collect static files so Nginx can serve them (as app so ownership is correct)
gosu app python manage.py collectstatic --noinput --clear 2>/dev/null || true
# Run Gunicorn as root so the control server can create its sockets
exec "$@"
