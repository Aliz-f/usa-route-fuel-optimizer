#!/bin/bash
set -e
# Collect static files so Nginx can serve them (volume may be empty on first run)
python manage.py collectstatic --noinput --clear 2>/dev/null || true
exec "$@"
