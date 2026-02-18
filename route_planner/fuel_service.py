import json
import os
from functools import lru_cache

import numpy as np
import pandas as pd
from django.conf import settings


GEOCODED_JSON_PATH = os.path.join(settings.BASE_DIR, "data", "fuel_geocoded.json")


def load_geocoded_dict():
    """
    Load persisted City_State -> [lat, lon] from disk.
    No network calls. Returns {} if file missing (API stays fast).
    """
    if not os.path.isfile(GEOCODED_JSON_PATH):
        return {}
    try:
        with open(GEOCODED_JSON_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


@lru_cache(maxsize=1)
def load_fuel_data():
    """
    Load and preprocess fuel data once at startup.
    For duplicate OPIS IDs, keep the cheapest price.
    """
    csv_path = os.path.join(settings.BASE_DIR, 'data', 'fuel_prices.csv')
    
    df = pd.read_csv(csv_path)
    
    # Clean up whitespace in city names
    df['City'] = df['City'].str.strip()
    df['Truckstop Name'] = df['Truckstop Name'].str.strip()
    
    # For duplicate locations (same OPIS ID), keep cheapest price
    df = df.sort_values('Retail Price').drop_duplicates(
        subset=['OPIS Truckstop ID'], 
        keep='first'
    )
    
    df = df.reset_index(drop=True)
    
    return df


def find_nearest_cheap_stops(
    point_lat: float,
    point_lon: float,
    fuel_df: pd.DataFrame,
    radius_miles: float = 50,
    top_n: int = 5
) -> list:
    """
    Find cheapest fuel stops within radius_miles of a given point.
    Uses vectorized haversine for speed.
    
    Returns list of dicts with stop info.
    """
    # Haversine vectorized
    lat1 = np.radians(point_lat)
    lon1 = np.radians(point_lon)
    lat2 = np.radians(fuel_df['lat'].values)
    lon2 = np.radians(fuel_df['lon'].values)
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    
    EARTH_RADIUS_MILES = 3958.8
    distances = EARTH_RADIUS_MILES * c
    
    fuel_df = fuel_df.copy()
    fuel_df['distance_from_point'] = distances
    
    # Filter within radius
    nearby = fuel_df[fuel_df['distance_from_point'] <= radius_miles]
    
    if nearby.empty:
        return []
    
    # Sort by price (cheapest first), then distance
    nearby = nearby.sort_values(['Retail Price', 'distance_from_point'])
    
    top_stops = nearby.head(top_n)
    
    return top_stops.to_dict('records')