from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from .fuel_service import load_fuel_data
from .optimizer import make_cache_key, optimize_fuel_stops
from .route_service import geocode_location, get_route


def home(request):
    """Render the frontend page (Jinja2 template)."""
    return render(request, 'route_planner/index.html', {
        'csrf_token': get_token(request),
    })


def health(request):
    """Health check for load balancers and Docker. Returns 200 if app is up; 503 if cache is down."""
    try:
        payload = {"status": "ok", "cache": "unknown"}
        status_code = 200
        redis_url = getattr(settings, "REDIS_URL", None)
        if redis_url and str(redis_url).strip():
            try:
                cache.set("health_check", 1, 10)
                cache.get("health_check")
                payload["cache"] = "ok"
            except Exception as e:
                payload["cache"] = "error"
                payload["cache_error"] = str(e)[:200]
                status_code = 503
        return JsonResponse(payload, status=status_code)
    except Exception:
        return JsonResponse({"status": "error", "message": "health check failed"}, status=500)


class RouteOptimizerView(APIView):
    """
    POST /api/route/optimize/
    
    Body:
    {
        "start": "Chicago, IL",
        "end": "Los Angeles, CA"
    }
    """
    
    def post(self, request):
        start = request.data.get('start', '').strip()
        end = request.data.get('end', '').strip()
        
        if not start or not end:
            return Response(
                {'error': 'Both start and end locations are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Require ORS API key for routing/geocoding
        api_key = getattr(settings, "ORS_API_KEY", None)
        if not api_key or not str(api_key).strip():
            return Response(
                {
                    "error": (
                        "Routing service is not configured. Set ORS_API_KEY in your .env file. "
                        "Get a free key at https://openrouteservice.org/dev/#/signup"
                    )
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Cache full response to avoid repeated API calls
        cache_key = make_cache_key("full_route", f"{start}|{end}")
        cached_response = cache.get(cache_key)
        if cached_response:
            return Response(cached_response)
        
        try:
            # Step 1: Geocode start and end (may use cached results)
            start_coords = geocode_location(start)
            end_coords = geocode_location(end)
            
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            return Response(
                {'error': f'Geocoding failed: {str(e)}'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        try:
            # Step 2: Get route from ORS
            route_data = get_route(start_coords, end_coords)
            
        except Exception as e:
            return Response(
                {'error': f'Routing failed: {str(e)}'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        
        try:
            # Step 3: Load fuel data (cached in memory after first load)
            fuel_df = load_fuel_data()
            
            # Step 4: Optimize fuel stops
            optimization = optimize_fuel_stops(
                route_coords=route_data['polyline_coords'],
                total_distance_miles=route_data['total_distance_miles'],
                fuel_df=fuel_df
            )
            
        except Exception as e:
            return Response(
                {'error': f'Optimization failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        
        # Build response
        response_data = {
            'route': {
                'start': {
                    'location': start,
                    'lat': start_coords[0],
                    'lon': start_coords[1]
                },
                'end': {
                    'location': end,
                    'lat': end_coords[0],
                    'lon': end_coords[1]
                },
                'total_distance_miles': optimization['total_distance_miles'],
                'estimated_duration_hours': round(
                    route_data['duration_seconds'] / 3600, 2
                ),
                # Polyline for map rendering (encoded for smaller payload)
                'polyline': encode_polyline(route_data['polyline_coords']),
                # Raw coords for easy frontend map rendering
                'waypoints': sample_coords(route_data['polyline_coords'], 200),
            },
            'fuel_optimization': {
                'fuel_stops': optimization['fuel_stops'],
                'segments': optimization['segments'],
                'summary': {
                    'total_fuel_stops': len(optimization['fuel_stops']),
                    'total_distance_miles': optimization['total_distance_miles'],
                    'total_gallons_needed': optimization['total_gallons'],
                    'average_price_per_gallon': optimization['avg_price_per_gallon'],
                    'total_fuel_cost_usd': optimization['total_fuel_cost_usd'],
                    'vehicle_mpg': optimization['mpg'],
                    'vehicle_max_range_miles': optimization['vehicle_range_miles'],
                }
            }
        }
        
        # Cache full response for 30 minutes
        cache.set(cache_key, response_data, 60 * 30)
        
        return Response(response_data, status=status.HTTP_200_OK)


def encode_polyline(coords: list) -> str:
    """Encode coords to Google polyline format for compact transmission."""
    import polyline as pl
    return pl.encode(coords)


def sample_coords(coords: list, max_points: int = 200) -> list:
    """Sample route coordinates to reduce payload size."""
    if len(coords) <= max_points:
        return [{'lat': c[0], 'lon': c[1]} for c in coords]
    
    step = len(coords) // max_points
    sampled = coords[::step]
    
    return [{'lat': c[0], 'lon': c[1]} for c in sampled]