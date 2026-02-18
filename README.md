# Route & Fuel Optimizer

API and web app for planning driving routes in the USA with cost-effective fuel stop suggestions (500 mi range, 10 MPG). Uses OpenRouteService for routing and a provided fuel-price dataset.

**Live demo:** [http://usa-fuel-optimizer.aliznet.ir:9090/](http://usa-fuel-optimizer.aliznet.ir:9090/)

## Local development

```bash
cp .env.example .env   # set ORS_API_KEY and optionally SECRET_KEY
uv sync                # or: pip install -r requirements.txt
python manage.py runserver
```

Open http://127.0.0.1:8000/

## Deployment (Docker)

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full guide. Quick start:

```bash
cp .env.example .env   # set ORS_API_KEY and SECRET_KEY
docker compose up -d --build
```

App: http://localhost:9090/

Stack: **Django (Gunicorn)** + **Redis** (cache) + **Nginx** (reverse proxy and static files).
