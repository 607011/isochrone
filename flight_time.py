"""Faustformel für die reine Flugzeit aus der Großkreisdistanz.

OpenFlights-Faustformel, kalibriert für 100-10.000 Meilen:
30 Minuten Grundzeit plus 1 Stunde pro 500 Meilen.
"""

from config import BASE_MINUTES, MINUTES_PER_BLOCK, MILES_PER_BLOCK


def estimate_flight_hours(distance_miles: float) -> float:
    minutes = BASE_MINUTES + (distance_miles / MILES_PER_BLOCK) * MINUTES_PER_BLOCK
    return minutes / 60
