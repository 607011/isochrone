"""Rule-of-thumb formula for pure flight time from the great-circle distance.

OpenFlights rule of thumb, calibrated for 100-10,000 miles:
30 minutes base time plus 1 hour per 500 miles.
"""

from config import BASE_MINUTES, MINUTES_PER_BLOCK, MILES_PER_BLOCK


def estimate_flight_hours(distance_miles: float) -> float:
    minutes = BASE_MINUTES + (distance_miles / MILES_PER_BLOCK) * MINUTES_PER_BLOCK
    return minutes / 60
