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

# Auflösung der gespeicherten PNGs. Höher = schärfer, aber Dateigröße und
# Renderzeit skalieren etwa quadratisch mit.
MAP_DPI = 150

# Flughafen-/Hafen-Punkte standardmäßig einblenden? Aus, da sonst auch
# Flughäfen ohne jeden Flugnetz-Nutzen (z.B. ohne einzige Route in
# routes.csv, siehe MEMO.md) unkommentiert als Punkt erscheinen -
# gezielt per --airports/--ports einblendbar.
SHOW_AIRPORTS = False
SHOW_PORTS = False

# --- "--galton"-Modus: geglättete, diskrete Farbbänder statt Kachel-Mosaik ---
# Gesamtspanne der Farbskala in Stunden (CLI: --max-hours), von 0 bis hier
# gleichmäßig in Bänder aufgeteilt - danach der dunkelste Farbton, statt die
# Skala weiter zu strecken. Bewusst derselbe Default-Wert wie COLOR_CAP_HOURS
# weiter unten (für den nicht-diskreten Modus), damit sich die
# Standardausgabe durch die Einführung dieses Schalters nicht ändert.
GALTON_MAX_HOURS = 48

# Anzahl der Bänder bei --cmap galton (interpolierte Palette) - kein eigener
# CLI-Schalter, da das eher zum Look der Palette gehört als zur Reichweite
# der Skala. Bei --cmap galton10 ist die Anzahl ohnehin durch die zehn festen
# Palettenfarben vorgegeben. 6 Bänder (bei GALTON_MAX_HOURS=48 also 8h breit)
# sind klar als 5 ineinander übergehende Farbfamilien lesbar, wie im
# Original - mehr Bänder würden das Sampling der zehn Ankerfarben so dicht
# machen, dass sie kaum noch von --cmap galton10 zu unterscheiden wären.
GALTON_NUM_BANDS = 6

# Nachbarschafts-Mittelung auf dem H3-Gitter selbst (1 Ring) glättet zu
# schwach, um Galtons handgezeichnete, glatte Bänder nachzubilden - das
# Bandmuster folgt sonst weiter dem kleinräumigen Rauschen der Rohdaten
# (Sahara/Amazonas: fleckig statt konzentrischer Ringe). Deshalb werden
# die Werte stattdessen auf ein reguläres Lat/Lon-Raster interpoliert und
# dort mit einem echten Gauß-Filter geglättet, bevor `contourf` daraus
# zusammenhängende Bänder zeichnet - siehe MEMO.md.
GALTON_GRID_DEG = 0.25       # Auflösung des Zwischenrasters
GALTON_SIGMA_DEG = 3.0       # Gauß-Glättungsradius (Standardabweichung)

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

# --- --heli/--jetpack (friction_map_from_point.py): Luftlinie statt
# Friction-Graph für die Einstiegs-Etappe Startpunkt -> Flughafen, dafür
# mit begrenzter Reichweite (anders als das unbegrenzte Flugnetz). ---
# Reisegeschwindigkeit angelehnt an leichte/mittlere Hubschrauber
# (Bell 429, Airbus H145: real ca. 220-260 km/h), Reichweite eher
# konservativ für diese Klasse ohne Zwischentanken (Robinson R44 ~560 km,
# Bell 407 ~650 km).
HELI_SPEED_KMH = 220
HELI_RANGE_KM = 500

# Reale treibstoffbetriebene Jetpacks (Jetpack Aviation JB-10, Bell
# Rocket Belt) erreichen kurzzeitig ca. 100+ km/h, halten das aber nur
# wenige Minuten durch (Flugdauer ca. 5-10 min) - daraus die Reichweite:
# 100 km/h * 10 min ≈ 17 km, aufgerundet.
JETPACK_SPEED_KMH = 100
JETPACK_RANGE_KM = 20

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
# PORTS_CSV ist der unveränderte Rohdatensatz, nur für
# fix_ports_coordinates.py relevant (siehe dort). Die normale Pipeline
# liest PORTS_CORRECTED_CSV.
PORTS_CSV = Path("ports.csv")
PORTS_CORRECTED_CSV = Path("ports_corrected.csv")
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

# --- Typografie (siehe plot_h3_map.py: TITLE_FONT/CONTINENT_FONT/CITY_FONT) ---
# Playfair Display ist eine Variable-Font-Datei - matplotlib kann deren
# Gewichtsachse nicht ansteuern, daher die statische Bold-Instanz
# (per fonttools varLib.instancer erzeugt), nicht die Variable-Datei selbst.
PLAYFAIR_BOLD_PATH = "fonts/PlayfairDisplay-Bold.ttf"
TITLE_FONT_FALLBACK_FAMILY = "serif"  # falls die Playfair-Datei fehlt
# Echtes Baskerville ist keine freie Schrift und war zuvor nur über macOS'
# Systeminstallation verfügbar (Nutzer auf anderen Betriebssystemen hätten
# stillschweigend einen Fallback-Font bekommen). Libre Baskerville (Impallari
# Type, SIL Open Font License, siehe fonts/LibreBaskerville-OFL.txt) ist eine
# gemeinfrei nutzbare, dem Original nachempfundene Alternative - genau wie
# bei Playfair Display statische Instanzen aus der Variable-Font-Datei
# extrahiert (Bold aus der Roman-, Regular aus der Italic-Achse).
CONTINENT_FONT_PATH = "fonts/LibreBaskerville-Bold.ttf"
CITY_FONT_PATH = "fonts/LibreBaskerville-Italic.ttf"
CONTINENT_FONT_FALLBACK_FAMILY = "serif"  # falls die Font-Datei fehlt
CITY_FONT_FALLBACK_FAMILY = "serif"

TITLE_FONT_SIZE = 18
CONTINENT_FONT_SIZE = 14
CITY_FONT_SIZE = 7.5
CITY_MARKER_SIZE = 2
