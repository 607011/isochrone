"""Zeichnet die H3-Kacheln, eingefärbt nach Reisezeit ab London.

Kacheln ohne Hub im Suchradius (siehe main_h3.py) bleiben unbemalt,
statt eine erfundene Reisezeit zu zeigen.
"""

import os

if "SSL_CERT_FILE" not in os.environ:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()

import h3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.collections import PolyCollection
from matplotlib.colors import LinearSegmentedColormap, ListedColormap, Normalize
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter
from matplotlib.transforms import Bbox
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
import numpy as np
import pandas as pd
from global_land_mask import globe
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

# Papierfarbe, wie sie ein gealterter Druck von 1881 hätte - liegt
# zwischen den zwei vom Nutzer vorgegebenen Werten rgb(220,212,183) und
# rgb(215,212,191).
BACKGROUND_COLOR = "#dad4bb"

# Typografie im Stil alter Kartendrucke: Playfair Display für die
# Hauptüberschrift, Baskerville (macOS-Systemschrift) für Orts-/
# Kontinentnamen - Kontinente fett, Städte kursiv. Schriftnamen und
# -größen stehen in config.py, damit man sie ohne Codeänderung anpassen
# kann, siehe MEMO.md.
if os.path.exists(config.PLAYFAIR_BOLD_PATH):
    fm.fontManager.addfont(config.PLAYFAIR_BOLD_PATH)
    TITLE_FONT = fm.FontProperties(fname=config.PLAYFAIR_BOLD_PATH)
else:
    TITLE_FONT = fm.FontProperties(family=config.TITLE_FONT_FALLBACK_FAMILY, weight="bold")
CONTINENT_FONT = fm.FontProperties(family=config.CONTINENT_FONT_FAMILY, weight="bold")
CITY_FONT = fm.FontProperties(family=config.CITY_FONT_FAMILY, style="italic")

# Direkt von der Originalkarte abgelesene RGB-Werte (dunkler/heller Ton
# je Farbe), nicht mehr nur per Augenmaß geschätzt wie der erste Versuch.
# Reihenfolge folgt der Legende: Grün (<10 Tage) - Gelb (10-20) -
# Rosa (20-30) - Blau (30-40) - Braun (>40 Tage), dunkel vor hell je
# Farbe. Nur die Farbstimmung ist nachgebildet, nicht die 10-Tage-
# Bandbreite selbst - die wäre für unsere Daten sinnlos, da schon die
# "<10 Tage"-Kategorie bei uns die gesamte Welt abdeckt (unser Maximum
# liegt bei 48h = 2 Tagen).
GALTON_COLORS = [
    "#697f75", "#d7d4bf",  # Grün dunkel/hell
    "#d1c498", "#dcd4b7",  # Gelb dunkel/hell
    "#ba9ca7", "#dfc6c0",  # Pink dunkel/hell
    "#8b98a9", "#aeb5be",  # Blau dunkel/hell
    "#a48d81", "#d2bea4",  # Braun dunkel/hell
]

# --cmap galton10: dieselben zehn Original-Farbwerte, aber als direkte,
# diskrete ListedColormap statt als Stützstellen einer interpolierten
# LinearSegmentedColormap (--cmap galton) - der Entfernungsstrahl bekommt
# so exakt zehn Stufen, eine Farbe pro Stufe, ohne Zwischentöne.
GALTON10_COLORS = GALTON_COLORS

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
    for name, lon, lat in _load_city_labels():
        ax.plot(
            lon, lat, marker="o", markersize=config.CITY_MARKER_SIZE, color=ANTHRACITE,
            transform=ccrs.PlateCarree(), zorder=6,
        )
        ax.text(
            lon + 1, lat, name, transform=ccrs.PlateCarree(), zorder=6,
            fontsize=config.CITY_FONT_SIZE, color=ANTHRACITE, ha="left", va="center",
            fontproperties=CITY_FONT,
        )


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


def plot_h3_map(
    h3_csv_path, travel_times_csv_path, ports_csv_path, png_path, origin_iatas,
    origin_label="London", dpi=config.MAP_DPI, show_airports=config.SHOW_AIRPORTS,
    show_ports=config.SHOW_PORTS, galton=False,
    band_hours=config.GALTON_BAND_HOURS, cmap_name=config.COLORMAP, labels=False, robinson=False,
    grid=False, title=False, lat_limits=None, origin_points=None, rivers=False,
    galton_sigma=config.GALTON_SIGMA_DEG,
):
    # low_memory=False: hub_id ist teils NaN (Landkacheln aus dem
    # Friction-Surface-Pfad haben keins, siehe friction_map_from_airport.py)
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
        # Im --galton-Modus exakt Galtons eigener Zuschnitt (80°N/60°S,
        # asymmetrisch - die Karte reichte nach Norden weiter als nach
        # Süden), sonst ein symmetrischer Standardwert.
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.Mercator())
        if lat_limits is not None:
            lat_max, lat_min = lat_limits
        else:
            lat_max, lat_min = (80, -60) if galton else (85, -85)
        # -180/180 exakt lässt Cartopys Mercator-Randberechnung auf NaN
        # laufen, daher ein winziges Inset.
        ax.set_extent([-179.9, 179.9, lat_min, lat_max], crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.LAND, facecolor="#f0f0e8", zorder=0)
    ax.add_feature(cfeature.OCEAN, facecolor="#d9e8f5", zorder=0)
    ax.coastlines(linewidth=COASTLINE_LINEWIDTH, color=ANTHRACITE, zorder=2)

    if rivers:
        # Natural-Earth-Layer für die großen, weltweit bedeutsamen Flüsse
        # (110m-Auflösung, wie bei den übrigen cfeature-Layern) - in
        # derselben Strichstärke wie die Landmassenumrisse, wie bei
        # Galtons Original, das auch nur die prominenten Flüsse zeigt.
        ax.add_feature(cfeature.RIVERS, edgecolor=ANTHRACITE, linewidth=COASTLINE_LINEWIDTH, zorder=2)

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
            gl.xlabel_style = {"color": ANTHRACITE, "fontsize": 8}
            gl.ylabel_style = {"color": ANTHRACITE, "fontsize": 8}
            plain_formatter = FuncFormatter(lambda v, pos: f"{v:g}")
            gl.xformatter = plain_formatter
            gl.yformatter = plain_formatter

    if galton:
        # Doppelte Rahmenlinie wie im Original: die Kartenumrandung ist
        # schon eine Linie (cartopys "geo"-Spine), eine zweite ergibt den
        # charakteristischen Doppelstrich drumherum. Der Abstand zwischen
        # beiden wird in Punkten statt Achsen-Bruchteilen berechnet (über
        # die Pixel-Bounding-Box der Achse), damit er horizontal und
        # vertikal exakt gleich groß ist - ein fester Achsen-Bruchteil
        # wäre das nicht, da die Karte nicht quadratisch ist.
        ax.spines["geo"].set_edgecolor(ANTHRACITE)
        ax.spines["geo"].set_linewidth(COASTLINE_LINEWIDTH)
        fig.canvas.draw()
        bbox_px = ax.get_window_extent(fig.canvas.get_renderer())
        gap_px = FRAME_GAP_PT * fig.dpi / 72.0
        inner_px = Bbox.from_extents(
            bbox_px.x0 + gap_px, bbox_px.y0 + gap_px, bbox_px.x1 - gap_px, bbox_px.y1 - gap_px,
        )
        inner_axes = inner_px.transformed(ax.transAxes.inverted())
        ax.add_patch(Rectangle(
            (inner_axes.x0, inner_axes.y0), inner_axes.width, inner_axes.height,
            transform=ax.transAxes, fill=False, edgecolor=ANTHRACITE, linewidth=COASTLINE_LINEWIDTH, zorder=5,
        ))

    # Wie bei Galtons Original: ab COLOR_CAP_HOURS wird der dunkelste
    # Farbton vergeben, statt die Skala linear bis zum tatsächlichen
    # Maximum (mehrere Tage Seezeit mitten im Ozean) zu strecken.
    if cmap_name == "galton10":
        # ListedColormap statt LinearSegmentedColormap: exakt zehn feste
        # Farben, keine Zwischentöne - eine direkte Palette statt
        # Stützstellen für eine Interpolation.
        cmap = ListedColormap(GALTON10_COLORS)
    elif cmap_name == "galton":
        cmap = LinearSegmentedColormap.from_list("galton", GALTON_COLORS)
    else:
        cmap = matplotlib.colormaps[cmap_name].copy()

    if galton:
        # contourf statt Kachel-Mosaik: siehe _build_galton_grid für die
        # Begründung (H3-Nachbarschaftsmittel glättet zu lokal, um
        # Galtons handgezeichnete Bänder nachzubilden).
        lon_grid, lat_grid, galton_values = _build_galton_grid(covered, sigma_deg=galton_sigma)
        if cmap_name == "galton10":
            # Exakt zehn gleich breite Stufen - eine je Palettenfarbe -,
            # unabhängig von --band-hours.
            boundaries = np.linspace(0, config.COLOR_CAP_HOURS, len(GALTON10_COLORS) + 1)
        else:
            boundaries = np.arange(0, config.COLOR_CAP_HOURS + band_hours, band_hours)
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

    cbar = fig.colorbar(mappable, ax=ax, orientation="horizontal", pad=0.05, shrink=0.6, extend="max")
    cbar.set_label(f"Reisezeit ab {origin_label} in Stunden")
    if galton:
        cbar.ax.xaxis.label.set_fontproperties(TITLE_FONT)

    if title:
        resolution = h3.get_resolution(covered["h3_index"].iloc[0]) if len(covered) else "?"
        if galton and cmap_name == "galton10":
            detail = f"10 feste Stufen, geglättet (Gauß-Radius {galton_sigma}°)"
        elif galton:
            detail = f"{band_hours}h-Bänder, geglättet (Gauß-Radius {galton_sigma}°)"
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

    if labels:
        _draw_labels(ax)

    fig.savefig(png_path, dpi=dpi, bbox_inches="tight", facecolor=BACKGROUND_COLOR)
    print(f"Karte gespeichert unter {png_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Auflösung des PNGs")
    parser.add_argument("--airports", action="store_true", help="Flughafen-Punkte einblenden (standardmäßig aus)")
    parser.add_argument("--ports", action="store_true", help="Hafen-Punkte einblenden (standardmäßig aus)")
    parser.add_argument(
        "--galton", action="store_true",
        help="Retro-Look: geglättete, diskrete Farbbänder statt stufenloser Skala",
    )
    parser.add_argument(
        "--band-hours", type=float, default=config.GALTON_BAND_HOURS,
        help="Bandbreite in Stunden im --galton-Modus (0-4, 4-8, ...), ignoriert von --cmap galton10",
    )
    parser.add_argument(
        "--galton-sigma", type=float, default=config.GALTON_SIGMA_DEG,
        help=f"Gauß-Glättungsradius in Grad im --galton-Modus (Standardabweichung, Standard {config.GALTON_SIGMA_DEG}°) - "
             "größer = weicher/verwaschener, kleiner = schärfer/näher am Rohraster",
    )
    parser.add_argument(
        "--cmap", default=config.COLORMAP,
        help="Farbpalette. Standard: viridis_r (Standard-Matplotlib, perzeptuell gleichmaessig). "
             "Weitere perzeptuell gleichmaessige Optionen: plasma_r, inferno_r, magma_r, cividis_r "
             "(oder ohne '_r' fuer umgekehrte Farbrichtung, oder jeder andere matplotlib-Colormap-Name). "
             "'galton': interpolierte, an das Original angelehnte Palette. "
             "'galton10': dieselben zehn Originalfarben als feste, nicht interpolierte Palette "
             "(zusammen mit --galton: exakt zehn Stufen statt --band-hours).",
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
             "ohne Angabe: 80,-60 unter --galton, sonst 85,-85",
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
        band_hours=args.band_hours, cmap_name=args.cmap, labels=args.labels, robinson=args.robinson,
        grid=args.grid, title=args.title, lat_limits=args.lat_limits, rivers=args.rivers,
        galton_sigma=args.galton_sigma,
    )
