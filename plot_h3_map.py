"""Zeichnet die H3-Kacheln, eingefärbt nach Reisezeit ab London.

Kacheln ohne Hub im Suchradius (siehe main_h3.py) bleiben unbemalt,
statt eine erfundene Reisezeit zu zeigen.
"""

import os
import textwrap

if "SSL_CERT_FILE" not in os.environ:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()

import h3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.collections import PolyCollection
from matplotlib.colors import ListedColormap, Normalize
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter
from matplotlib.transforms import Bbox
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
import numpy as np
import pandas as pd
from adjustText import adjust_text
from global_land_mask import globe
from PIL import Image, ImageColor
from scipy.ndimage import gaussian_filter
from sklearn.neighbors import BallTree

import config

# Kacheln, deren Eckpunkte-Längengrade (unkorrigiert) mehr als das hier
# überspannen, liegen an einem Pol - dort laufen alle Längengrade
# zusammen, das ist keine Antimeridian-Überquerung. Die "+360"-Korrektur
# für echte Antimeridian-Fälle würde solche Kacheln zu einem absurd
# breiten Riesenpolygon aufblähen, das große Teile der Karte verdeckt.
POLE_DEGENERACY_THRESHOLD_DEG = 300

# Küstenlinien und Beschriftung in Anthrazit statt Grau/Schwarz - näher
# am scharfen, gestochenen Druckbild von Galtons Original.
ANTHRACITE = "#2b2e33"
COASTLINE_LINEWIDTH = 0.7

# Abstand des Längen-/Breitengrad-Rasters für --grid, in Grad.
GRID_STEP_DEG = 20

# Abstand zwischen den beiden Linien des --galton-Doppelrahmens, in
# Punkten statt Achsen-Bruchteilen - so ist der Abstand in beide
# Richtungen exakt gleich groß, unabhängig vom (nicht-quadratischen)
# Seitenverhältnis der Karte.
FRAME_GAP_PT = 3.0

# Strichstärke des --galton-Rahmens (beide Linien) - kräftiger als die
# übrige Linienführung (COASTLINE_LINEWIDTH), wie im Original, dessen
# Rahmen deutlich dicker als die Küstenlinien wirkt.
FRAME_LINEWIDTH = 1.4

# Papierfarbe, wie sie ein gealterter Druck von 1881 hätte - liegt
# zwischen den zwei vom Nutzer vorgegebenen Werten rgb(220,212,183) und
# rgb(215,212,191).
BACKGROUND_COLOR = "#dad4bb"

# Typografie im Stil alter Kartendrucke: Playfair Display für die
# Hauptüberschrift, Libre Baskerville (gebundelt, siehe config.py) für
# Orts-/Kontinentnamen - Kontinente fett, Städte kursiv. Schriftnamen und
# -größen stehen in config.py, damit man sie ohne Codeänderung anpassen
# kann, siehe MEMO.md.
if os.path.exists(config.PLAYFAIR_BOLD_PATH):
    fm.fontManager.addfont(config.PLAYFAIR_BOLD_PATH)
    TITLE_FONT = fm.FontProperties(fname=config.PLAYFAIR_BOLD_PATH)
else:
    TITLE_FONT = fm.FontProperties(family=config.TITLE_FONT_FALLBACK_FAMILY, weight="bold")
if os.path.exists(config.CONTINENT_FONT_PATH):
    fm.fontManager.addfont(config.CONTINENT_FONT_PATH)
    CONTINENT_FONT = fm.FontProperties(fname=config.CONTINENT_FONT_PATH)
else:
    CONTINENT_FONT = fm.FontProperties(family=config.CONTINENT_FONT_FALLBACK_FAMILY, weight="bold")
if os.path.exists(config.CITY_FONT_PATH):
    fm.fontManager.addfont(config.CITY_FONT_PATH)
    CITY_FONT = fm.FontProperties(fname=config.CITY_FONT_PATH)
else:
    CITY_FONT = fm.FontProperties(family=config.CITY_FONT_FALLBACK_FAMILY, style="italic")
if os.path.exists(config.BODY_FONT_PATH):
    fm.fontManager.addfont(config.BODY_FONT_PATH)
    BODY_FONT = fm.FontProperties(fname=config.BODY_FONT_PATH)
else:
    BODY_FONT = fm.FontProperties(family=config.BODY_FONT_FALLBACK_FAMILY)
if os.path.exists(config.EXPLANATION_TITLE_FONT_PATH):
    fm.fontManager.addfont(config.EXPLANATION_TITLE_FONT_PATH)
    EXPLANATION_TITLE_FONT = fm.FontProperties(fname=config.EXPLANATION_TITLE_FONT_PATH)
else:
    EXPLANATION_TITLE_FONT = fm.FontProperties(
        family=config.EXPLANATION_TITLE_FONT_FALLBACK_FAMILY, weight="bold",
    )

# Direkt von der Originalkarte abgelesene RGB-Werte (dunkler/heller Ton
# je Farbe), nicht mehr nur per Augenmaß geschätzt wie der erste Versuch.
# Reihenfolge folgt der Legende: Grün (<10 Tage) - Gelb (10-20) -
# Rosa (20-30) - Blau (30-40) - Braun (>40 Tage), dunkel vor hell je
# Farbe. Nur die Farbstimmung ist nachgebildet, nicht die 10-Tage-
# Bandbreite selbst - die wäre für unsere Daten sinnlos, da schon die
# "<10 Tage"-Kategorie bei uns die gesamte Welt abdeckt (unser Maximum
# liegt bei 48h = 2 Tagen).
GALTON_COLORS = [
    "#697f75", "#9db5ab",  # Grün dunkel/hell
    "#d1c498", "#dcd4b7",  # Gelb dunkel/hell
    "#ba9ca7", "#dfc6c0",  # Pink dunkel/hell
    "#8b98a9", "#aeb5be",  # Blau dunkel/hell
    "#a48d81", "#d2bea4",  # Braun dunkel/hell
]

# --cmap galton5: eine auf fünf Farben reduzierte Palette - eine je
# Farbfamilie statt der zehn dunkel/hell-Paare von GALTON_COLORS. Keine
# einfache "jede zweite Farbe"-Auswahl, sondern die tatsächlichen
# Einzelschwatch-Farben aus Galtons Original-Legende (dunkles Grün, aber
# helles Gelb/Rosa/Blau/Braun - siehe Original-Legendenbild).
GALTON5_COLORS = [
    "#697f75",  # Grün dunkel
    "#dcd4b7",  # Gelb hell
    "#dfc6c0",  # Pink hell
    "#aeb5be",  # Blau hell
    "#d2bea4",  # Braun hell
]

# Grobe Kontinent-Beschriftungspositionen für --labels - ändern sich nie,
# deshalb fest hinterlegt statt aus einem Datensatz abgeleitet.
CONTINENT_LABELS = [
    ("NORTH AMERICA", -100, 45),
    ("SOUTH AMERICA", -60, -15),
    ("EUROPE", 15, 52),
    ("AFRICA", 20, 5),
    ("ASIA", 90, 50),
    ("AUSTRALIA", 135, -25),
]

# Nur die wichtigsten Weltstädte (SCALERANK 0 in Natural Earth's
# populated_places, ca. 27 Städte) - alle ~3200 Flughäfen zu beschriften
# wäre nur Buchstabenbrei, und Airport-Namen ("Heathrow") sind ohnehin
# keine Stadtnamen ("London").
CITY_LABEL_MAX_SCALERANK = 0


def _load_city_labels(max_scalerank=CITY_LABEL_MAX_SCALERANK):
    path = shpreader.natural_earth(resolution="110m", category="cultural", name="populated_places")
    records = shpreader.Reader(path).records()
    return [
        (r.attributes["NAME"], r.attributes["LONGITUDE"], r.attributes["LATITUDE"])
        for r in records
        if r.attributes["SCALERANK"] <= max_scalerank
    ]


def _draw_labels(ax):
    for name, lon, lat in CONTINENT_LABELS:
        ax.text(
            lon, lat, name, transform=ccrs.PlateCarree(), zorder=6,
            fontsize=config.CONTINENT_FONT_SIZE, color=ANTHRACITE, ha="center", va="center",
            fontproperties=CONTINENT_FONT,
        )
    city_texts = []
    for name, lon, lat in _load_city_labels():
        ax.plot(
            lon, lat, marker="o", markersize=config.CITY_MARKER_SIZE, color=ANTHRACITE,
            transform=ccrs.PlateCarree(), zorder=6,
        )
        city_texts.append(ax.text(
            lon + 1, lat, name, transform=ccrs.PlateCarree(), zorder=6,
            fontsize=config.CITY_FONT_SIZE, color=ANTHRACITE, ha="left", va="center",
            fontproperties=CITY_FONT,
        ))
    # Verschiebt nur sich gegenseitig überlappende Städtenamen auseinander
    # (dichte Regionen wie Rio/São Paulo) - küstenlinien-bewusstes
    # Ausweichen wäre ein größerer, separater Schritt (siehe MEMO.md).
    # Läuft in der jeweiligen Kartenprojektion (ax.transData über den
    # gemeinsamen Text-Transform, siehe adjustText-Quelltext), nicht in
    # Lon/Lat, daher automatisch für Mercator und Robinson gleichermaßen
    # korrekt.
    adjust_text(city_texts, ax=ax)


def _cell_polygon_lonlat(h3_index):
    boundary = h3.cell_to_boundary(h3_index)  # Tupel von (lat, lon)
    lons = [lon for _, lon in boundary]
    lats = [lat for lat, _ in boundary]
    span = max(lons) - min(lons)
    if span > POLE_DEGENERACY_THRESHOLD_DEG:
        return None
    if span > 180:  # Kachel liegt auf dem Antimeridian
        lons = [lon + 360 if lon < 0 else lon for lon in lons]
    return list(zip(lons, lats))


def _project_polygons(verts_lonlat, projection):
    """Projiziert alle Kachel-Vertices in einem Rutsch statt Polygon für Polygon.

    `PolyCollection(..., transform=ccrs.PlateCarree())` lässt Cartopy jedes
    Polygon einzeln über den generischen, Shapely-basierten Trace-Algorithmus
    (für beliebige, ggf. Antimeridian-kreuzende Geometrien) reprojizieren -
    bei hunderttausenden kleinen Sechsecken der dominante Kostenfaktor
    (>95% der Renderzeit, siehe MEMO.md). H3-Kacheln sind aber klein und
    (nach der Antimeridian-Korrektur in _cell_polygon_lonlat) nie
    selbst-überschneidend, brauchen also nicht den generischen Trace-Pfad -
    ein einziger vektorisierter `transform_points()`-Aufruf über alle
    Eckpunkte auf einmal reicht und ist um Größenordnungen schneller, weil
    er einmal statt 280.000-mal in die PROJ-Bibliothek wechselt.
    """
    counts = [len(v) for v in verts_lonlat]
    flat_lonlat = np.array([pt for v in verts_lonlat for pt in v])
    flat_xy = projection.transform_points(ccrs.PlateCarree(), flat_lonlat[:, 0], flat_lonlat[:, 1])[:, :2]
    splits = np.cumsum(counts)[:-1]
    return np.split(flat_xy, splits)


def _nan_gaussian_filter(grid, sigma_px):
    """Gauß-Filter, der NaN-Bereiche ignoriert statt sie einzumischen.

    Standard-Trick: fehlende Werte durch 0 ersetzen, sowohl die Werte
    als auch eine 0/1-Gültigkeitsmaske glätten, dann durcheinander
    teilen - so verwässern NaN-Zellen (z.B. See beim Land-Durchlauf)
    das Ergebnis nicht, sie fallen einfach aus dem gewichteten Mittel.
    mode=("nearest", "wrap"): an den Polen nicht über den Rand hinaus
    spiegeln, aber am Datumsgrenze nahtlos um die Welt herum glätten.
    """
    valid = ~np.isnan(grid)
    filled = np.where(valid, grid, 0.0)
    smoothed_values = gaussian_filter(filled, sigma_px, mode=("nearest", "wrap"))
    smoothed_weight = gaussian_filter(valid.astype(float), sigma_px, mode=("nearest", "wrap"))
    with np.errstate(invalid="ignore", divide="ignore"):
        result = smoothed_values / smoothed_weight
    result[smoothed_weight < 1e-6] = np.nan
    return result


def _build_galton_grid(covered_df, grid_deg=config.GALTON_GRID_DEG, sigma_deg=config.GALTON_SIGMA_DEG):
    """Reguläres, weichgezeichnetes Lat/Lon-Raster für contourf statt Kacheln.

    Nachbarschafts-Mittelung auf dem H3-Gitter selbst glättet zu lokal,
    um Galtons handgezeichnete, glatte Bänder nachzubilden (siehe
    config.py). Stattdessen: Kachelwerte per Nearest-Neighbor auf ein
    reguläres Raster übertragen, Land und Wasser GETRENNT mit einem
    echten Gauß-Filter glätten (sonst verschmiert die Küstenlinie), dann
    wieder zusammensetzen.
    """
    lon = np.arange(-180, 180, grid_deg)
    lat = np.arange(-90, 90, grid_deg)
    lon_grid, lat_grid = np.meshgrid(lon, lat)

    tree = BallTree(np.radians(covered_df[["lat", "lon"]].to_numpy()), metric="haversine")
    _, idx = tree.query(np.radians(np.column_stack([lat_grid.ravel(), lon_grid.ravel()])), k=1)
    nearest_values = covered_df["reisezeit_stunden"].to_numpy()[idx.ravel()].reshape(lon_grid.shape)

    is_land_grid = globe.is_land(lat_grid, lon_grid)
    sigma_px = sigma_deg / grid_deg

    land_grid = np.where(is_land_grid, nearest_values, np.nan)
    sea_grid = np.where(is_land_grid, np.nan, nearest_values)
    land_smoothed = _nan_gaussian_filter(land_grid, sigma_px)
    sea_smoothed = _nan_gaussian_filter(sea_grid, sigma_px)

    values = np.where(is_land_grid, land_smoothed, sea_smoothed)
    return lon_grid, lat_grid, values


def parse_lat_limits(s):
    """CLI-Parser für '--lat-limits=80,-60' (Norden,Süden) -> (80.0, -60.0)."""
    north_str, south_str = s.split(",")
    return float(north_str), float(south_str)


def _sketch(artist):
    """Lässt einen Linien-/Patch-Artist leicht 'handgezeichnet' wackeln statt
    geometrisch perfekt zu wirken - matplotlibs eingebauter Mechanismus
    hinter plt.xkcd(), hier gezielt nur auf einzelne Artists angewendet
    statt global. Wirkt auf jeden Artist mit set_sketch_params (Cartopys
    FeatureArtist/Gridliner und matplotlib-Patches gleichermaßen)."""
    artist.set_sketch_params(
        scale=config.RETRO_SKETCH_SCALE, length=config.RETRO_SKETCH_LENGTH,
        randomness=config.RETRO_SKETCH_RANDOMNESS,
    )


def _draw_galton_color_legend(fig, ax, boundaries, swatch_colors, paired):
    """Farberklärung im Stil von Galtons Original (1881): eine einzelne
    knappe, horizontal zentrierte Zeile 'Explanation of colours.' gefolgt
    von Farbfeld+Bereich je Band ('0-8h.', '8-16h.', ..., 'more than 48h.'
    für das letzte, offene Band - extend='max' im contourf-Aufruf gibt
    allem darüber ohnehin dieselbe Farbe), statt eines stufenlosen
    Farbbalkens mit eigener Achse und Achsenbeschriftung - nimmt dadurch
    deutlich weniger Höhe ein. Bei paired=True (--cmap galton) werden je
    zwei aufeinanderfolgende Farben (dunkel/hell derselben Farbfamilie, siehe
    GALTON_COLORS) als ein zusammenhängendes Doppelfeld mit einer
    gemeinsamen Bereichsangabe gruppiert, genau wie im Original (fünf
    benannte Farbfamilien, nicht zehn Einzeltöne).

    Layout in Figure-Koordinaten statt ax.transAxes, da die Zeile UNTER der
    Kartenachse sitzt, außerhalb ihrer eigenen Bounding Box - x-Positionen
    werden zunächst bei x=0 sequentiell aus den tatsächlich gerenderten
    Text-/Feldbreiten aufsummiert (fig.canvas.draw() + get_window_extent(),
    derselbe Trick wie beim --galton-Doppelrahmen weiter oben, da
    Textbreiten je nach Schriftart/-größe nicht im Voraus bekannt sind),
    dann als Ganzes um die Gesamtbreite verschoben, um unter der Kartenachse
    zentriert zu erscheinen - die Publikationszeile darunter wird separat
    anhand ihrer eigenen (kürzeren) Breite zentriert.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fig_w_px, fig_h_px = fig.bbox.width, fig.bbox.height

    ax_bbox = ax.get_position()
    ax_center = (ax_bbox.x0 + ax_bbox.x1) / 2
    y = ax_bbox.y0 - 0.05
    gap = config.GALTON_LEGEND_GAP_PT * fig.dpi / 72.0
    swatch_w = config.GALTON_LEGEND_SWATCH_WIDTH_PT * fig.dpi / 72.0
    swatch_h = config.GALTON_LEGEND_SWATCH_HEIGHT_PT * fig.dpi / 72.0

    artists = []
    x = 0.0

    def place_text(s, fontproperties=TITLE_FONT, fontsize=config.GALTON_LEGEND_FONT_SIZE):
        nonlocal x
        t = fig.text(
            x, y, s, fontproperties=fontproperties, fontsize=fontsize,
            color=ANTHRACITE, va="center", ha="left",
        )
        fig.canvas.draw()
        artists.append(t)
        x += (t.get_window_extent(renderer).width + gap) / fig_w_px

    def place_swatch(color):
        nonlocal x
        r = Rectangle(
            (x, y - (swatch_h / 2) / fig_h_px), swatch_w / fig_w_px, swatch_h / fig_h_px,
            transform=fig.transFigure, facecolor=color, edgecolor=ANTHRACITE,
            linewidth=COASTLINE_LINEWIDTH, zorder=10,
        )
        _sketch(r)
        fig.add_artist(r)
        artists.append(r)
        x += swatch_w / fig_w_px

    place_text("Explanation of colours.")

    n = len(boundaries) - 1
    step = 2 if paired else 1
    n_entries = n // step
    for entry in range(n_entries):
        i = entry * step
        place_swatch(swatch_colors[i])
        if paired:
            place_swatch(swatch_colors[i + 1])
        x += gap / fig_w_px

        is_last = entry == n_entries - 1
        # Auf ganze Stunden gerundet - nur für die Anzeige, die
        # tatsächlichen Bandgrenzen (boundaries, contourf-Level) bleiben
        # unangetastet, nur diese Beschriftung wird geglättet.
        lower_h = round(boundaries[i])
        upper_h = round(boundaries[i + step])
        # Beim letzten, offenen Band bezieht sich "more than" auf das obere
        # Ende der Skala (max_hours), nicht auf den Bandanfang - sonst würde
        # z.B. --max-hours=40 bei fünf Bändern (8h je Band) "more than 32h."
        # zeigen statt "more than 40h.", obwohl die Skala selbst bis 40h
        # geht und erst darüber (extend="max") derselbe Farbton greift.
        label = f"more than {upper_h}h." if is_last else f"{lower_h}-{upper_h} hours."
        place_text(label)

    total_width = x - gap / fig_w_px
    offset = ax_center - total_width / 2
    for artist in artists:
        if isinstance(artist, Rectangle):
            artist.set_x(artist.get_x() + offset)
        else:
            px, py = artist.get_position()
            artist.set_position((px + offset, py))

    footer_fontsize = config.GALTON_LEGEND_FONT_SIZE * 2 / 3
    footer = fig.text(
        0, y - 0.028, "Published by heise Medien, 2026.", fontproperties=CITY_FONT,
        fontsize=footer_fontsize, color=ANTHRACITE, va="center", ha="left",
    )
    fig.canvas.draw()
    footer_width = footer.get_window_extent(renderer).width / fig_w_px
    footer.set_position((ax_center - footer_width / 2, y - 0.028))


def _draw_galton_explanation(fig, ax, origin_label, legend, heli, jetpack):
    """Erklärungstext im Stil von Galtons Original (1881, siehe MEMO.md) -
    fest unten links in der Kartenecke verankert (Phase 14zY), nicht zu
    verwechseln mit der separaten Farberklärung unterhalb der Karte
    (_draw_galton_color_legend). Die Ursprungs-Legende (der Stern) wird
    stattdessen HIER, am Ende dieser Funktion, über den Kasten gestapelt
    (`legend.set_bbox_to_anchor()`) - umgekehrt zur früheren Anordnung, wo
    der Kasten über der an ihrer festen Ecke verbleibenden Legende
    stand. Grund: der Kasten soll immer an derselben, vorhersagbaren
    Stelle stehen, während die Legende (deren Höhe je nach Airport-/Port-
    Anzeige variiert) sich flexibel daran ausrichtet - nicht umgekehrt.
    War zwischenzeitlich (Phase 14zQ) im Indischen Ozean verankert, weil
    die damals noch breitere Box an dieser Stelle pazifische Inseln
    (Samoa) verdeckte - seit die Attribution auf zwei Zeilen umbricht
    (Phase 14zR) ist die Box schmal genug, um wieder links auf der Karte
    zu passen, ohne dorthin zu ragen.

    Anders als Galtons pauschales "showing the shortest number of days
    journey from London by the quickest through routes and using such
    further conveyances as are available without unreasonable cost"
    beschreibt der Text genau das, was dieses Modell tatsächlich
    berechnet: eine kombinierte Flug-/Boden-/See-Reisezeit ab dem
    gewählten Startpunkt (nicht zwangsläufig London), in Stunden statt
    Tagen (unser Maximum liegt bei rund 48h statt Galtons mehreren
    Wochen), als striktes Dijkstra-Minimum statt einer Ermessensfrage
    "ohne unangemessene Kosten". Die einzige tatsächlich im Modell
    vorhandene Kulanz-Annahme ist TRANSFER_HOURS je Umstieg - das tritt
    an die Stelle von Galtons vagem "local preparations have been made
    and other circumstances are favourable".

    Alle Zeilen sind auf eine gemeinsame Mittelachse zentriert, bis auf
    den Fließtext-Absatz: matplotlib kennt keinen echten Blocksatz (der
    bräuchte Wort-für-Wort-Platzierung mit dynamisch berechnetem
    Wortabstand) - der Absatz bleibt daher pro Zeile linksbündig, aber
    als Ganzes (anhand seiner breitesten Zeile) auf dieselbe Mittelachse
    zentriert, statt komplett linksbündig wie zuvor. Die Mittelachse
    selbst liegt so, dass der HINTERGRUND der Box (nicht nur der Text -
    siehe pad_px-Verschiebung unten) als Ganzes linksbündig mit der
    Kartenecke abschließt, an der die Legende ursprünglich (vor dem
    Verschieben, siehe unten) stand - sonst würde die Box über deren
    linken Rand hinaus in die Gradzahlen am Kartenrand hineinragen
    (Textblock) bzw. sogar bis an den Kartenrahmen selbst reichen
    (Hintergrund, dessen eigenes Padding sonst darüber hinausragen
    würde).

    Positionierung wie bei der Farberklärung: Text wird zunächst
    unsichtbar an Platzhalter-Positionen erzeugt, um die tatsächlich
    gerenderten Breiten/Höhen zu kennen (fig.canvas.draw() +
    get_window_extent(), da diese von Schriftart/-größe abhängen), dann
    an die endgültige Position verschoben. Die Zeilen werden von unten
    nach oben in umgekehrter Lesereihenfolge gestapelt (Attribution
    zuerst, Titel zuletzt), weil jede neue Zeile über der vorherigen
    erscheint.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fig_w_px, fig_h_px = fig.bbox.width, fig.bbox.height
    legend_bbox = legend.get_window_extent(renderer)

    body = (
        f"showing the shortest number of hours’ journey from {origin_label} "
        "by the quickest available routes, combining scheduled flight "
        "connections with realistic road- and terrain-following travel "
        "time to and from the airport, and shipping time across open "
        f"water. Airport transfers are assumed to take {config.TRANSFER_HOURS:g} "
        "hours each; it is supposed that no other delays occur."
    )
    if heli or jetpack:
        body += (
            " Where a helicopter or jetpack is used for departure, its "
            "higher speed and limited range are accounted for."
        )
    body_lines = textwrap.wrap(body, width=config.EXPLANATION_BODY_WRAP_CHARS)

    # Jede Zeile (Body-Absatz UND die einzeiligen Elemente) wird zunächst
    # an Platzhalter-Position (0, 0) erzeugt, nur um ihre gerenderte
    # Breite zu kennen - die insgesamt breiteste bestimmt die Mittelachse
    # so, dass die Box als Ganzes linksbündig mit der Legende abschließt
    # (siehe Docstring), statt deren Mitte zu treffen.
    def measure(text_str, fontproperties, fontsize):
        t = fig.text(
            0, 0, text_str, fontproperties=fontproperties, fontsize=fontsize,
            color=ANTHRACITE, va="bottom", ha="left", zorder=6,
        )
        fig.canvas.draw()
        return t, t.get_window_extent(renderer).width

    body_artists = []
    max_body_width_px = 0.0
    for line_str in body_lines:
        t, width_px = measure(line_str, BODY_FONT, config.EXPLANATION_BODY_FONT_SIZE)
        max_body_width_px = max(max_body_width_px, width_px)
        body_artists.append(t)

    title_artist, title_width_px = measure("ISOCHRONE CHART", EXPLANATION_TITLE_FONT, config.EXPLANATION_TITLE_FONT_SIZE)
    subtitle_artist, subtitle_width_px = measure("FOR TRAVELLERS,", CONTINENT_FONT, config.EXPLANATION_SUBTITLE_FONT_SIZE)
    attr1_artist, attr1_width_px = measure("In the manner of", CONTINENT_FONT, config.EXPLANATION_BODY_FONT_SIZE)
    attr2_artist, attr2_width_px = measure(
        "Francis Galton, F.R.S. (1881).", CONTINENT_FONT, config.EXPLANATION_BODY_FONT_SIZE,
    )

    max_width_px = max(max_body_width_px, title_width_px, subtitle_width_px, attr1_width_px, attr2_width_px)
    # Der Textblock selbst startet um pad_px NACH legend_bbox.x0 - der
    # Hintergrund (bg_rect weiter unten) wird um denselben pad_px wieder
    # nach außen erweitert, sodass am Ende dessen sichtbarer linker Rand
    # exakt bei legend_bbox.x0 landet, statt pad_px darüber hinaus in
    # Richtung Kartenrand zu ragen.
    pad_px = config.EXPLANATION_BG_PAD_PT * fig.dpi / 72.0
    center_x_px = legend_bbox.x0 + pad_px + max_width_px / 2
    para_x = (center_x_px - max_body_width_px / 2) / fig_w_px

    x_center = center_x_px / fig_w_px
    # Startet an der festen Kartenecke (legend_bbox.y0, die Legende stand
    # dort ursprünglich per loc="lower left") statt oberhalb der Legende -
    # der Kasten übernimmt jetzt deren Eckposition, siehe Docstring. Wie
    # beim linken Rand: +pad_px, damit der Hintergrund nach seiner eigenen
    # Erweiterung um pad_px wieder exakt auf legend_bbox.y0 landet.
    y = (legend_bbox.y0 + pad_px) / fig_h_px
    line_gap_px = 2.0 * fig.dpi / 72.0
    para_gap_px = 4.0 * fig.dpi / 72.0
    all_artists = list(body_artists) + [title_artist, subtitle_artist, attr1_artist, attr2_artist]

    def place_centered(artist, extra_gap_px=0.0):
        nonlocal y
        artist.set_position((x_center, y))
        artist.set_ha("center")
        fig.canvas.draw()
        y += (artist.get_window_extent(renderer).height + line_gap_px + extra_gap_px) / fig_h_px

    # Fett statt kursiv (CONTINENT_FONT statt CITY_FONT) - liest sich eher
    # wie eine Signaturzeile. Auf zwei Zeilen umgebrochen statt einer
    # langen - macht die Box insgesamt schmaler, da diese Zeile sonst die
    # breiteste im ganzen Block wäre (breiter als jede Absatzzeile).
    place_centered(attr2_artist)
    place_centered(attr1_artist)

    for i, t in enumerate(reversed(body_artists)):
        is_top_line = i == len(body_artists) - 1
        t.set_position((para_x, y))
        fig.canvas.draw()
        extra_gap_px = para_gap_px if is_top_line else 0.0
        y += (t.get_window_extent(renderer).height + line_gap_px + extra_gap_px) / fig_h_px

    # "FOR TRAVELLERS," mit Serifen (CONTINENT_FONT) statt der serifenlosen
    # Titel-Groteskschrift - wie im Original, wo nur die Hauptüberschrift
    # serifenlos ist.
    place_centered(subtitle_artist, extra_gap_px=para_gap_px)
    place_centered(title_artist)

    # Hellerer Hintergrund für besseren Kontrast vor der (teils dunklen)
    # Karte - eine Fläche hinter allen Textelementen, anhand deren
    # Gesamt-Bounding-Box bemessen.
    fig.canvas.draw()
    bg_bbox = None
    for artist in all_artists:
        artist_bbox = artist.get_window_extent(renderer)
        bg_bbox = artist_bbox if bg_bbox is None else Bbox.union([bg_bbox, artist_bbox])
    bg_px = Bbox.from_extents(
        bg_bbox.x0 - pad_px, bg_bbox.y0 - pad_px, bg_bbox.x1 + pad_px, bg_bbox.y1 + pad_px,
    )
    bg_axes = bg_px.transformed(ax.transAxes.inverted())
    bg_rect = Rectangle(
        (bg_axes.x0, bg_axes.y0), bg_axes.width, bg_axes.height,
        transform=ax.transAxes, facecolor=config.EXPLANATION_BG_COLOR, edgecolor="none",
        alpha=config.EXPLANATION_BG_ALPHA, zorder=5, clip_on=False,
    )
    ax.add_patch(bg_rect)

    # Ursprungs-Legende jetzt über den Kasten schieben, statt an ihrer
    # ursprünglichen Eckposition zu belassen - loc="lower left" bleibt
    # dabei aktiv, nur der Ankerpunkt wandert auf die Kastenoberkante,
    # sodass die Legende weiterhin mit ihrer eigenen Unterkante links dort
    # andockt (set_bbox_to_anchor akzeptiert auch nur einen Punkt statt
    # einer vollen Bbox, interpretiert per loc).
    gap_axes = config.GALTON_LEGEND_GAP_PT * fig.dpi / 72.0 / ax.get_window_extent(renderer).height
    legend.set_bbox_to_anchor((bg_axes.x0, bg_axes.y1 + gap_axes), transform=ax.transAxes)
    fig.canvas.draw()


def _apply_retro_noise(png_path, strength=config.RETRO_NOISE_STRENGTH, seed=0):
    """Gealtertes Papier-Rauschen als Postprocessing übers fertige PNG -
    grobkörnige, hochskalierte Flecken (Stockflecken-artige Papiermarmorierung)
    plus feines Pixelrauschen (Kornstruktur), additiv gemischt und aufs Bild
    addiert. Deutlich einfacher als Rauschen ins Rendering selbst
    einzubauen, und unabhängig von Projektion/Auflösung/DPI - wirkt auf das
    bereits fertig zusammengesetzte Bild (Karte + Legende + Titel)."""
    img = Image.open(png_path).convert("RGB")
    w, h = img.size
    rng = np.random.default_rng(seed)
    coarse = rng.normal(0, 1, size=(h // 10 + 1, w // 10 + 1)).astype(np.float32)
    coarse = np.array(Image.fromarray(coarse, mode="F").resize((w, h), Image.BILINEAR))
    fine = rng.normal(0, 1, size=(h, w)).astype(np.float32)
    grain = 0.6 * coarse + 0.4 * fine
    grain = grain / (np.abs(grain).max() + 1e-9)
    arr = np.asarray(img, dtype=np.float32)
    arr += grain[..., None] * strength * 255
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    Image.fromarray(arr).save(png_path)


def _apply_paper_size(png_path, paper, dpi):
    """Setzt die fertig gerenderte (per bbox_inches="tight" eng
    zugeschnittene) Karte mittig auf eine Seite im gewählten Papierformat
    (--paper), statt sie zu verzerren oder zuzuschneiden - Leerraum oben
    und unten in BACKGROUND_COLOR, da unsere Karten deutlich breiter als
    hoch sind, Normseiten (DIN/US) aber ein viel schmaleres
    Seitenverhältnis haben. Reine Rasternachbearbeitung übers fertige PNG,
    wie schon _apply_retro_noise - vermeidet, die bestehende, bereits fein
    austarierte figsize/bbox_inches="tight"-Logik anzufassen, die sich
    automatisch an alle Inhalte (Titel, Legende, Erklärungskasten,
    Rahmen) anpasst, egal welche Flags gesetzt sind.

    Skaliert das zugeschnittene Bild dafür auf die volle Papierbreite
    (Querformat, da die Karte selbst breiter als hoch ist) - ein leichtes
    Hoch-/Herunterskalieren gegenüber der organisch gewachsenen
    Originalbreite ist unvermeidlich, sobald eine exakte Papiergröße
    erzwungen wird, aber bei den hier üblichen Auflösungen visuell nicht
    wahrnehmbar. Wird vor _apply_retro_noise aufgerufen (siehe
    plot_h3_map()), damit die Papiermaserung auch den neu hinzugekommenen
    Leerraum mit einschließt, statt dort unnatürlich glatt zu bleiben.
    """
    width_in, height_in = config.PAPER_SIZES_IN[paper]
    page_w_px, page_h_px = round(max(width_in, height_in) * dpi), round(min(width_in, height_in) * dpi)

    img = Image.open(png_path).convert("RGB")
    scale = page_w_px / img.width
    resized = img.resize((page_w_px, round(img.height * scale)), Image.LANCZOS)

    bg_rgb = ImageColor.getrgb(BACKGROUND_COLOR)
    page = Image.new("RGB", (page_w_px, page_h_px), bg_rgb)
    paste_y = max(0, (page_h_px - resized.height) // 2)
    page.paste(resized, (0, paste_y))
    page.save(png_path)


def plot_h3_map(
    h3_csv_path, travel_times_csv_path, ports_csv_path, png_path, origin_iatas,
    origin_label="London", dpi=config.MAP_DPI, show_airports=config.SHOW_AIRPORTS,
    show_ports=config.SHOW_PORTS, galton=False,
    max_hours=config.GALTON_MAX_HOURS, cmap_name=None, labels=False, robinson=False,
    grid=False, title=False, lat_limits=None, origin_points=None, rivers=False,
    galton_sigma=config.GALTON_SIGMA_DEG, heli=False, jetpack=False, paper=None,
):
    # --galton impliziert --rivers/--grid/--labels - der Retro-Look zeigt
    # Flüsse, das Gradnetz und die Kontinent-/Stadtbeschriftung ohnehin wie
    # im Original, ein separates Anfordern wäre nur eine unnötige
    # zusätzliche Angabe.
    rivers = rivers or galton
    grid = grid or galton
    labels = labels or galton
    # --galton impliziert außerdem --cmap galton (statt config.COLORMAP),
    # sofern --cmap nicht explizit gesetzt wurde - der Retro-Look soll
    # Galtons echte Originalfarben zeigen, nicht viridis_r.
    cmap_name = cmap_name or ("galton" if galton else config.COLORMAP)

    # low_memory=False: hub_id ist teils NaN (Landkacheln aus dem
    # Friction-Surface-Pfad haben keins, siehe friction_map_from_point.py)
    # und teils String (Häfen) - pandas' Chunk-weise Typ-Erkennung warnt
    # sonst über diese gemischte Spalte, die hier ohnehin nicht genutzt wird.
    df = pd.read_csv(h3_csv_path, low_memory=False)
    covered = df[df["reisezeit_stunden"].notna()].copy()

    airports_df = pd.read_csv(travel_times_csv_path)
    ports_df = pd.read_csv(ports_csv_path)
    # origin_points: für Startpunkte, die keine Flughäfen sind (siehe
    # friction_map_from_point.py) - direkt übergebene (lat, lon)-Paare
    # statt einer Suche in airports_df per IATA-Code.
    if origin_points is not None:
        origin_lats = [lat for lat, lon in origin_points]
        origin_lons = [lon for lat, lon in origin_points]
    else:
        origins = airports_df[airports_df["iata_code"].isin(origin_iatas)]
        origin_lats = origins["lat"]
        origin_lons = origins["lon"]

    fig = plt.figure(figsize=(16, 9))
    fig.patch.set_facecolor(BACKGROUND_COLOR)
    if robinson:
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.Robinson())
        ax.set_global()
    else:
        # Wie Galtons Original (1881) - Mercator kann die Pole nicht
        # darstellen (Distanz zum Pol wird unendlich), deshalb auf einen
        # Breitenbereich begrenzen statt ax.set_global(). Erklärt auch
        # den Original-Effekt, dass Grönland/Spitzbergen überproportional
        # groß wirken - eine bekannte Mercator-Verzerrung, kein Fehler.
        # Standardmäßig Galtons eigener Zuschnitt (80°N/60°S, asymmetrisch -
        # die Karte reichte nach Norden weiter als nach Süden), unabhängig
        # von --galton - nicht nur eine Stileigenheit des Retro-Looks,
        # sondern auch praktisch: schneidet das ohnehin stark verzerrte,
        # wenig aussagekräftige Antarktis großteils ab.
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.Mercator())
        lat_max, lat_min = lat_limits if lat_limits is not None else (80, -60)
        # -180/180 exakt lässt Cartopys Mercator-Randberechnung auf NaN
        # laufen, daher ein winziges Inset.
        ax.set_extent([-179.9, 179.9, lat_min, lat_max], crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.LAND, facecolor="#f0f0e8", zorder=0)
    ax.add_feature(cfeature.OCEAN, facecolor="#d9e8f5", zorder=0)
    coast = ax.coastlines(linewidth=COASTLINE_LINEWIDTH, color=ANTHRACITE, zorder=2)
    if galton:
        _sketch(coast)

    if rivers:
        # Natural-Earth-Layer für die großen, weltweit bedeutsamen Flüsse
        # (110m-Auflösung, wie bei den übrigen cfeature-Layern) - in
        # derselben Strichstärke wie die Landmassenumrisse, wie bei
        # Galtons Original, das auch nur die prominenten Flüsse zeigt.
        river_feature = ax.add_feature(cfeature.RIVERS, edgecolor=ANTHRACITE, linewidth=COASTLINE_LINEWIDTH, zorder=2)
        if galton:
            _sketch(river_feature)

    if grid or galton:
        # Im --galton-Modus sollen wie im Original 1881 die Gradzahlen
        # außen an den Rändern stehen, unabhängig davon, ob die inneren
        # Linien (--grid) sichtbar sind - daher Linien nur bei --grid
        # eingeblendet (alpha=0 statt Weglassen, damit die Ticks/Labels
        # trotzdem an den richtigen Stellen erscheinen), Labels nur bei
        # --galton. Cartopys Gridliner-Labels funktionieren nur bei
        # rechteckigen Projektionen (Mercator), nicht bei Robinson.
        draw_labels = galton and not robinson
        gl = ax.gridlines(
            xlocs=range(-180, 181, GRID_STEP_DEG), ylocs=range(-90, 91, GRID_STEP_DEG),
            linewidth=COASTLINE_LINEWIDTH, color=ANTHRACITE, linestyle="-",
            alpha=0.8 if grid else 0, zorder=2, draw_labels=draw_labels,
        )
        if draw_labels:
            # Wie im Original: Gradzahlen an allen vier Seiten, nicht nur
            # oben/seitlich - aber nur die nackte Zahl, ohne °/N/E/S/W.
            gl.top_labels = True
            gl.bottom_labels = True
            gl.left_labels = True
            gl.right_labels = True
            gl.xlabel_style = {"color": ANTHRACITE, "fontsize": 8, "fontproperties": CITY_FONT}
            gl.ylabel_style = {"color": ANTHRACITE, "fontsize": 8, "fontproperties": CITY_FONT}
            # Wie im Original: keine Vorzeichen, West/Süd sind an der
            # Position (Rand) erkennbar, nicht am Minus vor der Zahl.
            plain_formatter = FuncFormatter(lambda v, pos: f"{abs(v):g}")
            gl.xformatter = plain_formatter
            gl.yformatter = plain_formatter

    if galton:
        # Drei Linien insgesamt, wie im Original: ein dünner Doppelrahmen
        # direkt an der Karte (Spine + ein knapp innen liegendes Rectangle,
        # beide COASTLINE_LINEWIDTH), plus eine deutlich kräftigere äußere
        # Linie (FRAME_LINEWIDTH), die zusätzlich die Gradzahlen am Rand
        # umschließt statt sie unbegrenzt draußen stehen zu lassen.
        ax.spines["geo"].set_edgecolor(ANTHRACITE)
        ax.spines["geo"].set_linewidth(COASTLINE_LINEWIDTH)
        _sketch(ax.spines["geo"])
        fig.canvas.draw()
        # set_sketch_params() auf dem Gridliner-Objekt selbst wirkt nicht -
        # die tatsächlich gezeichneten Linien sind eigene LineCollection-
        # Artists (xline_artists/yline_artists), die erst beim ersten
        # canvas.draw() entstehen (siehe oben) und daher erst hier
        # erreichbar sind. gl existiert immer an dieser Stelle, da galton
        # (Bedingung dieses Blocks) die Bedingung des gridlines()-Blocks
        # weiter oben (grid or galton) impliziert.
        for line_artist in list(gl.xline_artists) + list(gl.yline_artists):
            _sketch(line_artist)
        renderer = fig.canvas.get_renderer()

        # Innerer Rahmen: knapp innerhalb der Spine, ergibt den dünnen
        # Doppelstrich direkt an der Karte.
        bbox_px = ax.get_window_extent(renderer)
        gap_px = FRAME_GAP_PT * fig.dpi / 72.0
        inner_px = Bbox.from_extents(
            bbox_px.x0 + gap_px, bbox_px.y0 + gap_px, bbox_px.x1 - gap_px, bbox_px.y1 - gap_px,
        )
        inner_axes = inner_px.transformed(ax.transAxes.inverted())
        inner_rect = Rectangle(
            (inner_axes.x0, inner_axes.y0), inner_axes.width, inner_axes.height,
            transform=ax.transAxes, fill=False, edgecolor=ANTHRACITE, linewidth=COASTLINE_LINEWIDTH, zorder=5,
        )
        _sketch(inner_rect)
        ax.add_patch(inner_rect)

        # Äußerer Rahmen: umschließt nicht nur die Kartenachse selbst,
        # sondern auch die Gradzahlen an ihrem Rand - deren tatsächliche
        # Ausdehnung ist erst nach dem Rendern bekannt (Schriftgröße,
        # Zeichenanzahl), daher per Bounding-Box-Vereinigung aller
        # Label-Artists statt eines geschätzten festen Abstands ermittelt.
        for label_artist in gl.label_artists:
            bbox_px = Bbox.union([bbox_px, label_artist.get_window_extent(renderer)])
        outer_px = Bbox.from_extents(
            bbox_px.x0 - gap_px, bbox_px.y0 - gap_px, bbox_px.x1 + gap_px, bbox_px.y1 + gap_px,
        )
        outer_axes = outer_px.transformed(ax.transAxes.inverted())
        outer_rect = Rectangle(
            (outer_axes.x0, outer_axes.y0), outer_axes.width, outer_axes.height,
            transform=ax.transAxes, fill=False, edgecolor=ANTHRACITE, linewidth=FRAME_LINEWIDTH, zorder=5,
            clip_on=False,
        )
        _sketch(outer_rect)
        ax.add_patch(outer_rect)

        # Signaturzeile wie im Original, das sich dort mit Kartograph
        # ("H. Sharbau, F.G.S. del.", unten links) und Lithograph
        # ("E. Weller. lith.", unten rechts) verewigt - direkt unter dem
        # äußeren Rahmen, in Achsen-Bruchteilen relativ zur Achsenhöhe
        # (nicht zur Figure-Höhe) umgerechnet, da outer_axes bereits in
        # ax.transAxes-Koordinaten vorliegt.
        ax_height_px = ax.get_window_extent(renderer).height
        gap_axes = (config.CREDITS_GAP_PT * fig.dpi / 72.0) / ax_height_px
        credits_y = outer_axes.y0 - gap_axes
        ax.text(
            outer_axes.x0, credits_y, "O. Lau, ed., c’t", transform=ax.transAxes,
            fontproperties=CITY_FONT, fontsize=config.CREDITS_FONT_SIZE, color=ANTHRACITE,
            va="top", ha="left", zorder=6, clip_on=False,
        )
        ax.text(
            outer_axes.x1, credits_y, "Claude, gen. AI, Anthropic", transform=ax.transAxes,
            fontproperties=CITY_FONT, fontsize=config.CREDITS_FONT_SIZE, color=ANTHRACITE,
            va="top", ha="right", zorder=6, clip_on=False,
        )

    # Wie bei Galtons Original: ab COLOR_CAP_HOURS wird der dunkelste
    # Farbton vergeben, statt die Skala linear bis zum tatsächlichen
    # Maximum (mehrere Tage Seezeit mitten im Ozean) zu strecken.
    if cmap_name == "galton5":
        # ListedColormap statt Interpolation: feste Farben, keine
        # Zwischentöne - eine direkte Palette statt Stützstellen für eine
        # Interpolation.
        cmap = ListedColormap(GALTON5_COLORS)
    elif cmap_name == "galton":
        cmap = ListedColormap(GALTON_COLORS)
    else:
        cmap = matplotlib.colormaps[cmap_name].copy()

    if galton:
        # contourf statt Kachel-Mosaik: siehe _build_galton_grid für die
        # Begründung (H3-Nachbarschaftsmittel glättet zu lokal, um
        # Galtons handgezeichnete Bänder nachzubilden).
        lon_grid, lat_grid, galton_values = _build_galton_grid(covered, sigma_deg=galton_sigma)
        # Bandanzahl folgt der Palettengröße: fünf gleich breite Stufen bei
        # --cmap galton5, sonst zehn (--cmap galton oder jede andere
        # Colormap im --galton-Modus) - eine feste Stufe je Palettenfarbe,
        # kein eigener CLI-Schalter für die Bandanzahl.
        n_bands = len(GALTON5_COLORS) if cmap_name == "galton5" else len(GALTON_COLORS)
        boundaries = np.linspace(0, max_hours, n_bands + 1)
        mappable = ax.contourf(
            lon_grid, lat_grid, galton_values, levels=boundaries, cmap=cmap, extend="max",
            transform=ccrs.PlateCarree(), zorder=1,
        )
        n_dropped = 0
    else:
        polygons = [_cell_polygon_lonlat(h) for h in covered["h3_index"]]
        keep = [p is not None for p in polygons]
        verts_lonlat = [p for p in polygons if p is not None]
        values = covered["reisezeit_stunden"].to_numpy()[keep]
        n_dropped = len(polygons) - len(verts_lonlat)
        verts = _project_polygons(verts_lonlat, ax.projection)

        norm = Normalize(vmin=0, vmax=config.COLOR_CAP_HOURS, clip=False)
        mappable = PolyCollection(
            verts, array=values, cmap=cmap, norm=norm,
            edgecolors="none", antialiased=False, zorder=1,
        )
        ax.add_collection(mappable)

    if show_airports:
        ax.scatter(
            airports_df["lon"], airports_df["lat"], c="#ff9d00", marker="o", s=4,
            linewidths=0, alpha=0.8, transform=ccrs.PlateCarree(), zorder=3, label="Flughafen",
        )
    if show_ports:
        ax.scatter(
            ports_df["lon"], ports_df["lat"], c="#ff00c8", marker="o", s=4,
            linewidths=0, alpha=0.8, transform=ccrs.PlateCarree(), zorder=3, label="Hafen",
        )
    ax.scatter(
        origin_lons, origin_lats, c="red", marker="*", s=200,
        transform=ccrs.PlateCarree(), zorder=4, label=origin_label,
    )

    if galton:
        # Wie im Original: diskrete Farbfelder mit Bereichsangabe statt
        # eines stufenlosen Farbbalkens, siehe _draw_galton_color_legend().
        n_bands = len(boundaries) - 1
        if cmap_name == "galton5":
            swatch_colors = GALTON5_COLORS
        elif cmap_name == "galton":
            swatch_colors = GALTON_COLORS
        else:
            swatch_colors = [cmap((i + 0.5) / n_bands) for i in range(n_bands)]
        _draw_galton_color_legend(fig, ax, boundaries, swatch_colors, paired=cmap_name == "galton")
    else:
        cbar = fig.colorbar(mappable, ax=ax, orientation="horizontal", pad=0.05, shrink=0.6, extend="max")
        cbar.set_label(f"Reisezeit ab {origin_label} in Stunden")

    if title:
        resolution = h3.get_resolution(covered["h3_index"].iloc[0]) if len(covered) else "?"
        if galton:
            detail = f"{n_bands} feste Stufen, geglättet (Gauß-Radius {galton_sigma}°)"
        else:
            detail = f"{len(covered)}/{len(df)} Kacheln abgedeckt, {n_dropped} Pol-Kacheln nicht darstellbar"
        ax.set_title(
            f"Erreichbarkeit ab {origin_label} — H3-Raster Res. {resolution}, Land+See ({detail})",
            fontproperties=TITLE_FONT, fontsize=config.TITLE_FONT_SIZE, color=ANTHRACITE,
        )
    legend = ax.legend(loc="lower left", markerscale=2)
    if galton:
        for text in legend.get_texts():
            text.set_fontproperties(TITLE_FONT)
    # Nur der Stern soll in der Legende kleiner erscheinen als auf der
    # Karte (dort bleibt er unverändert auffällig groß) - daher erst
    # nach dem automatischen Anlegen der Legende gezielt dieses eine
    # Handle verkleinern, statt am scatter()-Aufruf selbst zu drehen.
    # scatter()-Größen sind Flächen, keine Durchmesser - durch 4 statt
    # durch 2 teilen, damit der Stern optisch (im Durchmesser) halb so
    # groß wirkt.
    for handle, text in zip(legend.legend_handles, legend.get_texts()):
        if text.get_text() == origin_label:
            handle.set_sizes(handle.get_sizes() / 4)

    if galton:
        _draw_galton_explanation(fig, ax, origin_label, legend, heli, jetpack)

    if labels:
        _draw_labels(ax)

    fig.savefig(png_path, dpi=dpi, bbox_inches="tight", facecolor=BACKGROUND_COLOR)
    if paper:
        _apply_paper_size(png_path, paper, dpi)
    if galton:
        _apply_retro_noise(png_path)
    print(f"Map saved as {png_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Auflösung des PNGs")
    parser.add_argument(
        "--paper", choices=sorted(config.PAPER_SIZES_IN), default=None,
        help="Karte mittig auf eine Seite in diesem Format setzen (Querformat), mit Leerraum in "
             "BACKGROUND_COLOR oben/unten statt eines beliebigen, vom Inhalt abhaengigen "
             "Seitenverhaeltnisses - ohne --paper bleibt es wie bisher beim engen Zuschnitt um "
             "den tatsaechlichen Inhalt (bbox_inches=\"tight\").",
    )
    parser.add_argument("--airports", action="store_true", help="Flughafen-Punkte einblenden (standardmäßig aus)")
    parser.add_argument("--ports", action="store_true", help="Hafen-Punkte einblenden (standardmäßig aus)")
    parser.add_argument(
        "--galton", action="store_true",
        help="Retro-Look: geglättete, diskrete Farbbänder statt stufenloser Skala",
    )
    parser.add_argument(
        "--max-hours", type=float, default=config.GALTON_MAX_HOURS,
        help="Gesamtspanne der Farbskala in Stunden im --galton-Modus - ab hier der dunkelste "
             "Farbton statt weiterer Streckung. Gleichmaessig in zehn Baender aufgeteilt "
             "(bzw. fuenf feste bei --cmap galton5).",
    )
    parser.add_argument(
        "--galton-sigma", type=float, default=config.GALTON_SIGMA_DEG,
        help=f"Gauß-Glättungsradius in Grad im --galton-Modus (Standardabweichung, Standard {config.GALTON_SIGMA_DEG}°) - "
             "größer = weicher/verwaschener, kleiner = schärfer/näher am Rohraster",
    )
    parser.add_argument(
        "--cmap", default=None,
        help="Farbpalette. Standard: viridis_r (Standard-Matplotlib, perzeptuell gleichmaessig) - "
             "ausser mit --galton, dann Standard: galton. Weitere perzeptuell gleichmaessige "
             "Optionen: plasma_r, inferno_r, magma_r, cividis_r (oder ohne '_r' fuer umgekehrte "
             "Farbrichtung, oder jeder andere matplotlib-Colormap-Name). "
             "'galton': die zehn echten Original-Farbwerte als feste, nicht interpolierte Palette "
             "(zusammen mit --galton: zehn statt fuenf Stufen). "
             "'galton5': dieselbe Palette auf fuenf Farben reduziert, eine je Farbfamilie "
             "(zusammen mit --galton: fuenf statt zehn Stufen).",
    )
    parser.add_argument(
        "--labels", action="store_true",
        help="Kontinente und wichtigste Weltstädte beschriften, wie bei Galtons Original",
    )
    parser.add_argument(
        "--robinson", action="store_true",
        help="Robinson-Projektion statt der (seit Galtons Original) Standard-Mercator-Projektion",
    )
    parser.add_argument(
        "--grid", action="store_true",
        help=f"Längen-/Breitengrad-Raster in {GRID_STEP_DEG}°-Abständen einzeichnen",
    )
    parser.add_argument(
        "--title", action="store_true",
        help="Überschrift einblenden (standardmäßig aus)",
    )
    parser.add_argument(
        "--lat-limits", type=parse_lat_limits, default=None, metavar="NORD,SÜD",
        help="Breitengrad-Zuschnitt der Mercator-Karte, z.B. '80,-60' (wirkungslos bei --robinson); "
             "ohne Angabe: 80,-60 (Galtons eigener Zuschnitt, unabhängig von --galton)",
    )
    parser.add_argument(
        "--rivers", action="store_true",
        help="Große Flüsse einzeichnen (Natural Earth, 110m), in derselben Strichstärke wie die Küstenlinien",
    )
    args = parser.parse_args()

    plot_h3_map(
        config.OUTPUT_H3_CSV, config.OUTPUT_CSV, config.OUTPUT_PORTS_CSV,
        config.OUTPUT_H3_MAP_PNG, config.ORIGIN_AIRPORTS,
        dpi=args.dpi, show_airports=args.airports, show_ports=args.ports, galton=args.galton,
        max_hours=args.max_hours, cmap_name=args.cmap, labels=args.labels, robinson=args.robinson,
        grid=args.grid, title=args.title, lat_limits=args.lat_limits, rivers=args.rivers,
        galton_sigma=args.galton_sigma, paper=args.paper,
    )
