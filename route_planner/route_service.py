import requests
from django.conf import settings
from django.core.cache import cache

from .optimizer import make_cache_key


def _handle_ors_error(e, context: str) -> str:
    """Turn ORS/requests errors into a clear message for the API response."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        status_code = e.response.status_code
        try:
            body = e.response.json()
            msg = body.get("error", {}).get("message") or body.get("message") or (e.response.text[:200] if e.response.text else str(e))
        except Exception:
            msg = e.response.text[:200] if e.response.text else str(e)
        if status_code in (401, 403):
            return f"Invalid ORS API key. {context} Get a free key at https://openrouteservice.org/dev/#/signup"
        if status_code == 429:
            return "ORS rate limit exceeded. Please try again in a few minutes."
        return f"ORS {context} (HTTP {status_code}): {msg}"
    if isinstance(e, requests.RequestException):
        return f"Could not reach routing service: {e.__class__.__name__}. Check your network."
    return f"{context}: {e!s}"


def geocode_location(location: str) -> tuple:
    """
    Geocode a location string to (lat, lon) using ORS geocoding.
    Free, no extra API needed.
    """
    cache_key = make_cache_key("geocode", location)
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    url = "https://api.openrouteservice.org/geocode/search"
    params = {
        'api_key': settings.ORS_API_KEY,
        'text': location,
        'boundary.country': 'US',
        'size': 1
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
    except Exception as e:
        raise RuntimeError(_handle_ors_error(e, "geocoding failed"))
    
    data = response.json()
    
    if not data.get('features'):
        raise ValueError(f"Could not geocode location: {location}")
    
    coords = data['features'][0]['geometry']['coordinates']
    result = (coords[1], coords[0])  # (lat, lon)
    
    # Cache geocoding results for 24 hours
    cache.set(cache_key, result, 60 * 60 * 24)
    
    return result


def get_route(start_coords: tuple, end_coords: tuple) -> dict:
    """
    Get driving route from ORS. ONE API call.
    Returns:
        - total_distance_miles
        - duration_seconds  
        - polyline_coords: list of (lat, lon) tuples
        - bbox
    """
    cache_key = make_cache_key("route", f"{start_coords}{end_coords}")
    cached = cache.get(cache_key)
    if cached:
        return cached
    
    # Use /geojson path so response has "features"; plain /directions returns JSON with "routes"
    url = "https://api.openrouteservice.org/v2/directions/driving-hgv/geojson"

    headers = {
        "Authorization": settings.ORS_API_KEY,
        "Content-Type": "application/json",
    }

    body = {
        "coordinates": [
            [start_coords[1], start_coords[0]],  # ORS uses [lon, lat]
            [end_coords[1], end_coords[0]],
        ],
        "units": "mi",
    }
    
    try:
        response = requests.post(url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as e:
        raise RuntimeError(_handle_ors_error(e, "routing failed"))

    data = response.json()

    # ORS can return 200 with an error body (e.g. no route found, invalid params)
    if not data.get("features"):
        err = data.get("error") or {}
        msg = err.get("message") if isinstance(err, dict) else str(err)
        if not msg and isinstance(data.get("error"), str):
            msg = data["error"]
        raise RuntimeError(
            msg
            if msg
            else "No route returned. Check that start and end are in the USA and reachable by road."
        )

    feature = data["features"][0]
    props = feature.get("properties", {}).get("summary")
    if not props:
        raise RuntimeError("Routing failed: invalid response format from routing service.")

    # Extract coordinates from GeoJSON
    raw_coords = feature.get("geometry", {}).get("coordinates")
    if not raw_coords:
        raise RuntimeError("Routing failed: no geometry in route response.")
    coords_latlon = [(c[1], c[0]) for c in raw_coords]

    result = {
        "total_distance_miles": props["distance"],
        "duration_seconds": props["duration"],
        "polyline_coords": coords_latlon,
        "bbox": feature.get("bbox"),
    }

    # Cache route for 1 hour
    cache.set(cache_key, result, 60 * 60)

    return result