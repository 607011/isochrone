"""Zentrale Konfiguration für die Isochronenkarten-Berechnung.

Alles, was du später anpassen willst (Startflughäfen, Umstiegszeit,
Faustformel-Konstanten), steht hier gesammelt.
"""

import os
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

# --paper: Papierformate in Zoll (Breite, Höhe), Hochformat-Maße - die
# Karte selbst bleibt im eigenen, breiten Seitenverhältnis (siehe
# figsize in plot_h3_map.py) und wird nachträglich mittig auf eine
# Seite in diesem Format gesetzt (Querformat, da unsere Karten breiter
# als hoch sind), mit Leerraum in BACKGROUND_COLOR oben/unten statt
# verzerrt/zugeschnitten zu werden - siehe MEMO.md. DIN-Maße nach
# ISO 216, US-Maße nach ANSI/ASME Y14.1.
PAPER_SIZES_IN = {
    "a0": (33.11, 46.81),
    "a1": (23.39, 33.11),
    "a2": (16.54, 23.39),
    "a3": (11.69, 16.54),
    "a4": (8.27, 11.69),
    "a5": (5.83, 8.27),
    "a6": (4.13, 5.83),
    "letter": (8.5, 11.0),
    "legal": (8.5, 14.0),
    "tabloid": (11.0, 17.0),
}

# Flughafen-/Hafen-Punkte standardmäßig einblenden? Aus, da sonst auch
# Flughäfen ohne jeden Flugnetz-Nutzen (z.B. ohne einzige Route in
# routes.csv, siehe MEMO.md) unkommentiert als Punkt erscheinen -
# gezielt per --airports/--ports einblendbar.
SHOW_AIRPORTS = False
SHOW_PORTS = False

# Gesamtspanne der Farbskala in Stunden (CLI: --max-hours) - ab hier wird
# der dunkelste Farbton vergeben, statt die Skala linear bis zum
# tatsächlichen Maximum (mehrere Tage Seezeit mitten im Ozean) zu strecken -
# wie bei Galtons Original mit diskreten Farbbändern und einer letzten
# "und mehr"-Kategorie. Gilt für BEIDE Rendering-Modi: im normalen
# Kachel-Mosaik direkt als oberes Ende von Normalize() (vorher fälschlich
# fest auf die inzwischen entfernte Konstante COLOR_CAP_HOURS verdrahtet,
# --max-hours blieb dadurch dort wirkungslos), unter --galton zusätzlich
# gleichmäßig in Bänder aufgeteilt.
GALTON_MAX_HOURS = 48

# Nachbarschafts-Mittelung auf dem H3-Gitter selbst (1 Ring) glättet zu
# schwach, um Galtons handgezeichnete, glatte Bänder nachzubilden - das
# Bandmuster folgt sonst weiter dem kleinräumigen Rauschen der Rohdaten
# (Sahara/Amazonas: fleckig statt konzentrischer Ringe). Deshalb werden
# die Werte stattdessen auf ein reguläres Lat/Lon-Raster interpoliert und
# dort mit einem echten Gauß-Filter geglättet, bevor `contourf` daraus
# zusammenhängende Bänder zeichnet - siehe MEMO.md.
GALTON_GRID_DEG = 0.25       # Auflösung des Zwischenrasters
GALTON_SIGMA_DEG = 3.0       # Gauß-Glättungsradius (Standardabweichung)

# Kupferstich-Retro-Look, nur unter --galton: Linien (Küsten, Flüsse, Gitter,
# Rahmen) leicht "handgezeichnet" wackeln lassen statt sie geometrisch perfekt
# zu ziehen (matplotlibs eingebauter Artist.set_sketch_params(), derselbe
# Mechanismus wie hinter plt.xkcd()), plus ein gealtertes Papier-Rauschen als
# Postprocessing-Schritt übers fertige PNG. Werte per Sichtprobe bei
# config.MAP_DPI kalibriert: genug Wackeln/Körnung, um wie gestochen statt
# digital gezeichnet zu wirken, ohne die Lesbarkeit zu beeinträchtigen -
# siehe MEMO.md.
# randomness deutlich über matplotlibs eigenem Default (16) zu niedrig
# angesetzt ergibt eine beinahe perfekte, rhythmische Sinuswelle statt
# eines unregelmäßigen Zitterns - je höher, desto "zufälliger" wirkt die
# Wellung statt gleichförmig zu schwingen.
# scale/length sind laut matplotlib-Doku Pixel, nicht Punkte - werden in
# _sketch() (plot_h3_map.py) mit dpi/MAP_DPI skaliert, damit die Wellung bei
# einem anderen --dpi als hier kalibriert optisch gleich groß bleibt.
RETRO_SKETCH_SCALE = 0.1       # Amplitude der Linienwellung, in Pixeln bei MAP_DPI
RETRO_SKETCH_LENGTH = 15.0      # Wellenlänge der Linienwellung, in Pixeln bei MAP_DPI
RETRO_SKETCH_RANDOMNESS = 10.0  # Zufälligkeit der Wellung (dimensionsloser Faktor)
RETRO_NOISE_STRENGTH = 0.06     # Stärke des Papier-Rauschoverlays (0-1)

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
# Regular-Schnitt (nicht kursiv, nicht fett) - für den Fließtext der
# --galton-Erklärungsbox, die anders als Kontinent-/Städtenamen keine
# Auszeichnung braucht. Aus derselben Roman-Achse wie CONTINENT_FONT_PATH
# extrahiert, nur bei wght=400 statt 700.
BODY_FONT_PATH = "fonts/LibreBaskerville-Regular.ttf"
CONTINENT_FONT_FALLBACK_FAMILY = "serif"  # falls die Font-Datei fehlt
CITY_FONT_FALLBACK_FAMILY = "serif"
BODY_FONT_FALLBACK_FAMILY = "serif"

# Für die Überschrift der --galton-Erklärungsbox (_draw_galton_explanation):
# im Original eine kräftige, serifenlose Groteskschrift, breit statt eng
# laufend, ganz anders als der Rest der Kartentypografie (Playfair/Libre
# Baskerville, beides Serifen). Archivo (Google Fonts, SIL Open Font
# License, siehe fonts/Archivo-OFL.txt) hat eine Breiten- UND eine
# Gewichtsachse - per fonttools varLib.instancer eine statische Instanz bei
# maximaler Breite (wdth=125) und maximalem Gewicht (wght=900) erzeugt,
# dadurch breiter laufend als die eigenständige (schmalere) statische
# "Archivo Black"-Schnittdatei und näher am Original als das zwischenzeitlich
# probierte, zu eng laufende Anton.
EXPLANATION_TITLE_FONT_PATH = "fonts/ArchivoExpanded-Black.ttf"
EXPLANATION_TITLE_FONT_FALLBACK_FAMILY = "sans-serif"

TITLE_FONT_SIZE = 18
CONTINENT_FONT_SIZE = 14
CITY_FONT_SIZE = 7.5
CITY_MARKER_SIZE = 2

# --- Erklärungstext im --galton-Modus (siehe plot_h3_map.py:_draw_galton_explanation) ---
# Wie bei Galtons Original: ein knapper Erklärungstext auf der Karte selbst
# (nicht Teil der Farberklärung darunter), mit hellerem Hintergrund für
# besseren Kontrast vor der Karte, direkt über der Ursprungs-Legende (dem
# Stern) gestapelt. War zwischenzeitlich (zu breit für diese Position) im
# Indischen Ozean verankert - seit die Attribution auf zwei Zeilen umbricht
# wieder schmal genug für die ursprüngliche Position links.
EXPLANATION_TITLE_FONT_SIZE = 10
EXPLANATION_SUBTITLE_FONT_SIZE = 7.5
EXPLANATION_BODY_FONT_SIZE = 7
EXPLANATION_BODY_WRAP_CHARS = 34
EXPLANATION_BG_COLOR = "#e8e0cb"  # etwas dunkler als der erste Versuch (#f2ede0), aber immer noch heller als BACKGROUND_COLOR (#dad4bb)
EXPLANATION_BG_ALPHA = 0.85
EXPLANATION_BG_PAD_PT = 5.0

# --- Signaturzeile im --galton-Modus (siehe plot_h3_map.py:_draw_credits) ---
# Wie im Original, das sich unten links (Kartograph "H. Sharbau, F.G.S.
# del.") und unten rechts (Lithograph "E. Weller. lith.") direkt unter dem
# Kartenrahmen verewigt.
CREDITS_FONT_SIZE = 7.0
CREDITS_GAP_PT = 4.0

# --- Logo unten rechts (siehe plot_h3_map.py:_draw_logo) ---
# Auf JEDER Karte, nicht nur unter --galton - anders als die Signaturzeile
# oben, die den Kartenrahmen voraussetzt, den es nur im Retro-Look gibt.
LOGO_SVG_PATH = "assets/ct-logo.svg"
LOGO_GAP_PT = 4.0

# --- Farberklärung im --galton-Modus (siehe plot_h3_map.py:_draw_galton_color_legend) ---
# Wie im Original von 1881: eine einzelne, knappe Zeile "Explanation of
# colours." gefolgt von Farbfeld+Bereich je Band, statt eines stufenlosen
# Farbbalkens mit eigener Achse - nimmt dadurch deutlich weniger Höhe ein.
GALTON_LEGEND_FONT_SIZE = 10
GALTON_LEGEND_SWATCH_WIDTH_PT = 22
GALTON_LEGEND_SWATCH_HEIGHT_PT = 11
GALTON_LEGEND_GAP_PT = 6

# --- Web-Backend (siehe backend_server.py) ---
# Obergrenze gleichzeitig laufender Render-Jobs (ProcessPoolExecutor) -
# jeder Job ist CPU- und speicherintensiv (Dijkstra + Cartopy + Matplotlib),
# daher bewusst konservativ statt an der Kernanzahl orientiert. Per
# Umgebungsvariable ISOSCHRONE_MAX_JOBS überschreibbar, ohne Codeänderung
# (z.B. für einen leistungsfähigeren Host).
MAX_CONCURRENT_RENDER_JOBS = int(os.environ.get("ISOSCHRONE_MAX_JOBS", 2))
