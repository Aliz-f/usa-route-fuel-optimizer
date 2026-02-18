import hashlib
import json
import os
import time
from typing import List

import numpy as np
import pandas as pd
import requests

from .fuel_service import (
    find_nearest_cheap_stops,
    load_fuel_data,
    load_geocoded_dict,
    GEOCODED_JSON_PATH,
)


MAX_RANGE_MILES = 500
MPG = 10
# We want to refuel at ~400 miles to stay safe (80% of max range)
REFUEL_INTERVAL_MILES = 400
DEFAULT_CENTROID = (39.5, -98.35)


def make_cache_key(prefix: str, value: str) -> str:
    """
    Create a safe cache key by hashing the value.
    Avoids issues with spaces, special chars, etc.
    """
    hashed = hashlib.md5(value.encode("utf-8")).hexdigest()
    return f"{prefix}_{hashed}"


def haversine_miles(lat1, lon1, lat2, lon2):
    """Single point haversine distance in miles."""
    R = 3958.8
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2)**2
    return R * 2 * np.arcsin(np.sqrt(a))


def get_point_at_distance(coords: list, target_miles: float) -> tuple:
    """
    Walk along route coordinates until we've traveled target_miles.
    Returns (lat, lon) at that point along the route.
    """
    accumulated = 0.0
    
    for i in range(1, len(coords)):
        lat1, lon1 = coords[i-1]
        lat2, lon2 = coords[i]
        
        segment_dist = haversine_miles(lat1, lon1, lat2, lon2)
        
        if accumulated + segment_dist >= target_miles:
            # Interpolate within this segment
            remaining = target_miles - accumulated
            fraction = remaining / segment_dist if segment_dist > 0 else 0
            
            interp_lat = lat1 + fraction * (lat2 - lat1)
            interp_lon = lon1 + fraction * (lon2 - lon1)
            
            return (interp_lat, interp_lon)
        
        accumulated += segment_dist
    
    # If target exceeds route, return last point
    return coords[-1]


def get_fuel_df_with_coords(fuel_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add lat/lon to fuel dataframe from persisted file or state centroids.
    No external API calls — keeps API response fast.
    """
    geocoded = load_geocoded_dict()
    lats: List[float] = []
    lons: List[float] = []

    for _, row in fuel_df.iterrows():
        city_state = f"{row['City']}_{row['State']}"
        coords = geocoded.get(city_state)
        if coords is not None:
            lats.append(coords[0])
            lons.append(coords[1])
        else:
            lat, lon = STATE_CENTROIDS.get(row["State"], DEFAULT_CENTROID)
            lats.append(lat)
            lons.append(lon)

    out = fuel_df.copy()
    out["lat"] = lats
    out["lon"] = lons
    return out


def geocode_fuel_data(fuel_df: pd.DataFrame) -> pd.DataFrame:
    """
    Geocode fuel stops via Nominatim and persist to disk.
    Intended for use by management command only (prewarm). Uses 1 req/s for
    Nominatim policy. No calls in normal API request path.
    """
    geocoded = load_geocoded_dict()
    missing_keys: List[str] = []
    for _, row in fuel_df.iterrows():
        city_state = f"{row['City']}_{row['State']}"
        if city_state not in geocoded:
            missing_keys.append(city_state)

    # Deduplicate while preserving order
    seen = set()
    unique_missing = []
    for k in missing_keys:
        if k not in seen:
            seen.add(k)
            unique_missing.append(k)

    if unique_missing:
        headers = {"User-Agent": "FuelRouteOptimizer/1.0"}
        for city_state in unique_missing:
            city, state = city_state.rsplit("_", 1)
            query = f"{city}, {state}, USA"
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": query,
                "format": "json",
                "limit": 1,
                "countrycodes": "us",
            }
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=5)
                data = resp.json()
                if data:
                    lat = float(data[0]["lat"])
                    lon = float(data[0]["lon"])
                else:
                    lat, lon = STATE_CENTROIDS.get(state, DEFAULT_CENTROID)
            except Exception:
                lat, lon = STATE_CENTROIDS.get(state, DEFAULT_CENTROID)
            geocoded[city_state] = [lat, lon]
            time.sleep(1)  # Nominatim usage policy: 1 request per second

        data_dir = os.path.dirname(GEOCODED_JSON_PATH)
        if data_dir:
            os.makedirs(data_dir, exist_ok=True)
        with open(GEOCODED_JSON_PATH, "w") as f:
            json.dump(geocoded, f, indent=0)

    return get_fuel_df_with_coords(fuel_df)


def optimize_fuel_stops(
    route_coords: list,
    total_distance_miles: float,
    fuel_df: pd.DataFrame
) -> dict:
    """
    Main optimization function.
    
    Strategy:
    1. Divide route into segments of ~REFUEL_INTERVAL_MILES
    2. At each segment point, find cheapest nearby fuel stop
    3. Calculate total fuel cost
    
    Returns fuel stops and cost summary.
    """
    fuel_df_geo = get_fuel_df_with_coords(fuel_df)
    
    fuel_stops = []
    current_miles = 0
    
    # Always check start + every REFUEL_INTERVAL_MILES
    # (first stop is optional if route < 500 miles)
    
    waypoints_to_check = []
    
    if total_distance_miles <= MAX_RANGE_MILES:
        # Only need one fuel stop: cheapest along entire route
        # Check at 50%, 75% of route
        waypoints_to_check = [total_distance_miles * 0.5]
    else:
        # Multiple stops needed
        miles = REFUEL_INTERVAL_MILES
        while miles < total_distance_miles:
            waypoints_to_check.append(miles)
            miles += REFUEL_INTERVAL_MILES
    
    for waypoint_miles in waypoints_to_check:
        # Get the lat/lon at this distance along route
        point = get_point_at_distance(route_coords, waypoint_miles)
        
        # Find cheapest nearby stops
        nearby_stops = find_nearest_cheap_stops(
            point_lat=point[0],
            point_lon=point[1],
            fuel_df=fuel_df_geo,
            radius_miles=75,  # Search wider radius for better prices
            top_n=3
        )
        
        if not nearby_stops:
            # Expand search radius
            nearby_stops = find_nearest_cheap_stops(
                point_lat=point[0],
                point_lon=point[1],
                fuel_df=fuel_df_geo,
                radius_miles=150,
                top_n=3
            )
        
        if nearby_stops:
            best_stop = nearby_stops[0]  # Already sorted by price
            fuel_stops.append({
                'opis_id': best_stop['OPIS Truckstop ID'],
                'name': best_stop['Truckstop Name'],
                'address': best_stop['Address'],
                'city': best_stop['City'],
                'state': best_stop['State'],
                'lat': best_stop['lat'],
                'lon': best_stop['lon'],
                'retail_price_per_gallon': round(best_stop['Retail Price'], 3),
                'miles_from_start': round(waypoint_miles, 1),
                'alternatives': [
                    {
                        'name': s['Truckstop Name'],
                        'city': s['City'],
                        'state': s['State'],
                        'price': round(s['Retail Price'], 3),
                        'lat': s['lat'],
                        'lon': s['lon'],
                    }
                    for s in nearby_stops[1:]
                ]
            })
    
    # Calculate total fuel cost
    total_gallons = total_distance_miles / MPG
    
    if fuel_stops:
        avg_price = np.mean([s['retail_price_per_gallon'] for s in fuel_stops])
    else:
        # No stops found, use average from dataset
        avg_price = fuel_df_geo['Retail Price'].mean()
    
    total_cost = total_gallons * avg_price
    
    # Per-segment cost calculation
    segments = []
    prev_miles = 0
    
    for stop in fuel_stops:
        segment_miles = stop['miles_from_start'] - prev_miles
        gallons = segment_miles / MPG
        cost = gallons * stop['retail_price_per_gallon']
        segments.append({
            'from_miles': prev_miles,
            'to_miles': stop['miles_from_start'],
            'segment_miles': round(segment_miles, 1),
            'gallons_needed': round(gallons, 2),
            'cost_usd': round(cost, 2)
        })
        prev_miles = stop['miles_from_start']
    
    # Last segment (final stop to destination)
    if fuel_stops:
        last_segment_miles = total_distance_miles - prev_miles
        last_gallons = last_segment_miles / MPG
        last_cost = last_gallons * fuel_stops[-1]['retail_price_per_gallon']
        segments.append({
            'from_miles': prev_miles,
            'to_miles': round(total_distance_miles, 1),
            'segment_miles': round(last_segment_miles, 1),
            'gallons_needed': round(last_gallons, 2),
            'cost_usd': round(last_cost, 2)
        })
    
    return {
        'fuel_stops': fuel_stops,
        'total_gallons': round(total_gallons, 2),
        'total_distance_miles': round(total_distance_miles, 1),
        'avg_price_per_gallon': round(avg_price, 3),
        'total_fuel_cost_usd': round(total_cost, 2),
        'segments': segments,
        'vehicle_range_miles': MAX_RANGE_MILES,
        'mpg': MPG
    }


# US State centroids fallback
STATE_CENTROIDS = {
    'AL': (32.806671, -86.791130), 'AK': (61.370716, -152.404419),
    'AZ': (33.729759, -111.431221), 'AR': (34.969704, -92.373123),
    'CA': (36.116203, -119.681564), 'CO': (39.059811, -105.311104),
    'CT': (41.597782, -72.755371), 'DE': (39.318523, -75.507141),
    'FL': (27.766279, -81.686783), 'GA': (33.040619, -83.643074),
    'HI': (21.094318, -157.498337), 'ID': (44.240459, -114.478828),
    'IL': (40.349457, -88.986137), 'IN': (39.849426, -86.258278),
    'IA': (42.011539, -93.210526), 'KS': (38.526600, -96.726486),
    'KY': (37.668140, -84.670067), 'LA': (31.169960, -91.867805),
    'ME': (44.693947, -69.381927), 'MD': (39.063946, -76.802101),
    'MA': (42.230171, -71.530106), 'MI': (43.326618, -84.536095),
    'MN': (45.694454, -93.900192), 'MS': (32.741646, -89.678696),
    'MO': (38.456085, -92.288368), 'MT': (46.921925, -110.454353),
    'NE': (41.125370, -98.268082), 'NV': (38.313515, -117.055374),
    'NH': (43.452492, -71.563896), 'NJ': (40.298904, -74.521011),
    'NM': (34.840515, -106.248482), 'NY': (42.165726, -74.948051),
    'NC': (35.630066, -79.806419), 'ND': (47.528912, -99.784012),
    'OH': (40.388783, -82.764915), 'OK': (35.565342, -96.928917),
    'OR': (44.572021, -122.070938), 'PA': (40.590752, -77.209755),
    'RI': (41.680893, -71.511780), 'SC': (33.856892, -80.945007),
    'SD': (44.299782, -99.438828), 'TN': (35.747845, -86.692345),
    'TX': (31.054487, -97.563461), 'UT': (40.150032, -111.862434),
    'VT': (44.045876, -72.710686), 'VA': (37.769337, -78.169968),
    'WA': (47.400902, -121.490494), 'WV': (38.491226, -80.954453),
    'WI': (44.268543, -89.616508), 'WY': (42.755966, -107.302490),
}