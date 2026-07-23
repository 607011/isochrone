"""Land/water mask for H3 tile centers.

Prevents ocean tiles from getting a travel time that would imply an
overland route across water - the ground-time model in
nearest_airport.py assumes a road/rail link that doesn't exist there.
"""

from global_land_mask import globe


def is_land(lat, lon):
    return globe.is_land(lat, lon)
