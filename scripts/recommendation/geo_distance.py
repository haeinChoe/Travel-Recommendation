"""Geographic distance and coordinate validation utilities for POI matching."""

from __future__ import annotations

import math


EARTH_RADIUS_METERS = 6371000.0
KOREA_LAT_MIN = 33.0
KOREA_LAT_MAX = 39.0
KOREA_LON_MIN = 124.0
KOREA_LON_MAX = 132.5


def is_valid_korea_wgs84(lat: float | None, lon: float | None) -> bool:
    """Verify if (lat, lon) falls within the expected South Korea WGS84 bounding box."""
    if lat is None or lon is None:
        return False
    return KOREA_LAT_MIN <= lat <= KOREA_LAT_MAX and KOREA_LON_MIN <= lon <= KOREA_LON_MAX


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute the great-circle distance between two WGS84 points in meters."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_METERS * c
