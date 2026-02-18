# Deployment Guide

This document describes how to run the Route & Fuel Optimizer app using Docker Compose (Redis, Gunicorn, Nginx).

## Architecture

- **web** – Django app served by Gunicorn (1 worker, 1 thread). Uses Redis for cache when `REDIS_URL` is set.
- **redis** – Redis 7 with persistence (AOF). Used for geocode/route and response caching.
- **nginx** – Reverse proxy: serves `/static/`, proxies all other traffic to `web:8000`.

```
                    ┌─────────────┐
                    │   Nginx     │  :9090 (host)
                    │ (static +   │
                    │  reverse    │
                    │  proxy)     │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐      ┌────────┐
                    │   Gunicorn │◄────►│ Redis  │
                    │   (Django) │      │  :6379 │
                    └────────────┘      └────────┘
```

## Prerequisites

- Docker and Docker Compose (v2+)
- `.env` file with at least `ORS_API_KEY` and `SECRET_KEY` (see below)

## Quick Start (local)

1. **Create environment file**

   ```bash
   cp .env.example .env
   # Edit .env: set ORS_API_KEY and SECRET_KEY
   ```

2. **Build and run**

   ```bash
   docker compose up -d --build
   ```

3. **Open the app**

   - App: <http://localhost:9090/>
   - Health: <http://localhost:9090/health/>

## Deploy on a server (IPv4, no SSL)

Use this when the app runs on a VPS or dedicated server and you access it by the server’s IP (no domain, no HTTPS).

1. **On the server**, clone the repo and create `.env`:

   ```bash
   cd /path/to/ena-spotter
   cp .env.example .env
   ```

2. **Edit `.env`** and set at least:

   - `ORS_API_KEY` – your OpenRouteService key
   - `SECRET_KEY` – a long random string
   - **Server IP** – replace `203.0.113.10` with your server’s public IPv4:

   ```env
   ALLOWED_HOSTS=203.0.113.10,localhost,127.0.0.1,web
   CSRF_TRUSTED_ORIGINS=http://203.0.113.10,http://203.0.113.10:9090
   ```

3. **Start the stack**

   ```bash
   docker compose up -d --build
   ```

4. **Open in a browser**

   - App: `http://YOUR_SERVER_IP:9090/`
   - Health: `http://YOUR_SERVER_IP:9090/health/`

5. **Firewall**: ensure TCP port **9090** is open (e.g. `ufw allow 9090 && ufw reload`).

Nginx in the container listens on 80; Docker maps host port **9090** to it, so use `http://...:9090`. No SSL or domain is required.

## Deploy with a domain (no SSL)

You can use a domain name instead of an IP. Point your domain’s DNS A record to your server’s IPv4, then in `.env` set:

```env
ALLOWED_HOSTS=your-domain.com,www.your-domain.com,localhost,127.0.0.1,web
CSRF_TRUSTED_ORIGINS=http://your-domain.com,http://www.your-domain.com,http://your-domain.com:9090
```

Replace `your-domain.com` with your actual domain (e.g. `app.example.com`). Restart the stack: `docker compose up -d --build`. Open `http://your-domain.com:9090/` in a browser (app uses port **9090**). No SSL is required; use `http://` only.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ORS_API_KEY` | Yes | OpenRouteService API key ([free signup](https://openrouteservice.org/dev/#/signup)) |
| `SECRET_KEY` | Yes (prod) | Django secret key (e.g. 50+ char random string) |
| `DEBUG` | No | Set to `0` in production (default in compose) |
| `ALLOWED_HOSTS` | No | Comma-separated; compose sets `localhost,127.0.0.1,web` |
| `CSRF_TRUSTED_ORIGINS` | No | Comma-separated origins when using HTTPS |
| `REDIS_URL` | No | Set by docker-compose to `redis://redis:6379/0` |

## Useful Commands

```bash
# View logs
docker compose logs -f web
docker compose logs -f nginx

# Run management commands (e.g. prewarm geocoding)
docker compose exec web python manage.py prewarm_geocoding

# Collect static files (already done in Dockerfile; re-run if needed)
docker compose exec web python manage.py collectstatic --noinput

# Stop
docker compose down

# Stop and remove volumes
docker compose down -v
```

## Production Checklist

- [ ] Set strong `SECRET_KEY` in `.env`.
- [ ] Set `DEBUG=0` (default in compose).
- [ ] **Server (IPv4, no SSL):** set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` in `.env` to your server IP (see [Deploy on a server](#deploy-on-a-server-ipv4-no-ssl)).
- [ ] **With domain/HTTPS:** set `ALLOWED_HOSTS` to your domain(s) and `CSRF_TRUSTED_ORIGINS` to `https://yourdomain.com`; put HTTPS in front of Nginx (e.g. Let’s Encrypt).
- [ ] Optionally run `prewarm_geocoding` once to populate `data/fuel_geocoded.json` for better fuel-stop accuracy (data persisted in `data_volume` if you run the command and then restart, or bake into image).

## Health Check

- **Endpoint:** `GET /health/`
- **Response:** `200` with `{"status": "ok", "cache": "ok"}` when app and Redis are fine.
- **Response:** `503` with `{"status": "ok", "cache": "error", ...}` if Redis is unavailable.

Docker healthcheck for the `web` service uses this endpoint.
