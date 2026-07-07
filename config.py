"""Zentrale Konfiguration für die Isochronenkarten-Berechnung.

Alles, was du später anpassen willst (Startflughäfen, Umstiegszeit,
Faustformel-Konstanten), steht hier gesammelt.
"""

from pathlib import Path

# --- Pfade ---
ROUTES_CSV = Path("routes.csv")
AIRPORTS_CSV = Path("airports.csv")
OUTPUT_CSV = Path("travel_times.csv")
OUTPUT_MAP_PNG = Path("travel_times_map_london_airports_points.png")

# --- Darstellung der Punktkarte ---
COLORMAP = "viridis_r"  # _r: dunkel = weit weg, hell = nah

# Ab dieser Reisezeit (Stunden) wird der dunkelste Farbton vergeben, statt
# die Skala linear bis zum tatsächlichen Maximum zu strecken - wie bei
# Galtons Original mit diskreten Farbbändern und einer letzten
# "und mehr"-Kategorie.
COLOR_CAP_HOURS = 48

# --- Startflughäfen. Die schnellste Verbindung über alle wird gewählt. ---
ORIGIN_AIRPORTS = ["LHR", "LGW", "LCY", "STN", "LTN"]

# --- Flugzeit-Faustformel: BASE_MINUTES + MINUTES_PER_BLOCK je MILES_PER_BLOCK Meilen ---
BASE_MINUTES = 30
MINUTES_PER_BLOCK = 60
MILES_PER_BLOCK = 500

# --- Umstiegszeit pro Zwischenstopp, in Stunden ---
TRANSFER_HOURS = 1.5

# --- Erdradius für die Haversine-Formel, in Meilen bzw. Kilometern ---
EARTH_RADIUS_MILES = 3958.8
EARTH_RADIUS_KM = 6371.0088

# --- Codeshare-Flüge als eigene Kanten in der Topologie mitzählen? ---
INCLUDE_CODESHARE = True

# --- H3-Raster: Auflösung und maximaler Suchradius für Kandidaten-Flughäfen ---
H3_RESOLUTION = 4

# Seit Bodenzeit korrekt eingerechnet wird (siehe nearest_airport.py),
# ist der Suchradius keine willkürliche "Nähe"-Grenze mehr, sondern nur
# noch eine Performance-Obergrenze: Ein Flughafen kann einen näheren nur
# schlagen, wenn seine um GROUND_SPEED_KMH * (Distanzunterschied)
# aufgewogene Flugzeitersparnis das ausgleicht. Bei einer maximalen
# Flugzeitspanne von ~34h (siehe travel_times.csv) und 80 km/h
# Bodengeschwindigkeit kann kein Flughafen jenseits von ~2700 km
# Distanzunterschied mehr gewinnen - 3000 km Suchradius ist also
# praktisch "kein Limit mehr", nur ohne unnötigen Rechenaufwand.
MAX_AIRPORT_DISTANCE_KM = 3000

# --- Angenommene Bodengeschwindigkeit (Auto/Zug) zwischen Flughafen und Kachel ---
GROUND_SPEED_KMH = 80

OUTPUT_H3_CSV = Path("h3_travel_times.csv")
OUTPUT_H3_MAP_PNG = Path("h3_travel_times_map_london_h3_land_and_sea.png")

# --- Häfen (LINERLIB, github.com/blof/LINERLIB) ---
PORTS_CSV = Path("ports.csv")
OUTPUT_PORTS_CSV = Path("ports_travel_times.csv")

# Angenommene Schiffsgeschwindigkeit für die "letzte Meile" Hafen -> Wasserkachel.
SEA_SPEED_KMH = 35

# Suchradius für Häfen um eine Wasserkachel. Anders als bei Flughäfen soll
# JEDE Wasserkachel eine Reisezeit bekommen, auch mitten im Ozean - daher
# praktisch unbegrenzt (die maximale Großkreisdistanz auf der Erde beträgt
# ca. 20.015 km). Dass das für sehr entlegene Kacheln zu Seezeiten von
# mehreren Tagen führt, ist beabsichtigt und wird erst bei der Darstellung
# (plot_h3_map.py) mit einer gekappten Farbskala aufgefangen - wie bei
# Galtons Original, das ab einer Schwelle den dunkelsten Farbton vergibt,
# statt die Skala linear bis zum Extremwert gemeinsam zu strecken.
MAX_PORT_DISTANCE_KM = 20_015
