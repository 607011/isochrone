"""Land/Wasser-Maske für H3-Kachelzentren.

Verhindert, dass Ozean-Kacheln eine Reisezeit bekommen, die einen
Bodenweg über Wasser unterstellen würde - das Bodenzeit-Modell in
nearest_airport.py setzt eine Straße/Schiene voraus, die es dort nicht gibt.
"""

from global_land_mask import globe


def is_land(lat, lon):
    return globe.is_land(lat, lon)
