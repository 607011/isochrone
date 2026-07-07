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
from matplotlib.colors import LinearSegmentedColormap, Normalize
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

# Typografie im Stil alter Kartendrucke: Playfair Display für die
# Hauptüberschrift (Google Font, OFL-Lizenz, als statische Bold-Instanz
# aus der Variable-Font-Datei erzeugt - matplotlib kann keine
# Font-Achsen ansteuern), Baskerville (macOS-Systemschrift) für
# Orts-/Kontinentnamen - Kontinente fett, Städte kursiv.
PLAYFAIR_BOLD = "fonts/PlayfairDisplay-Bold.ttf"
if os.path.exists(PLAYFAIR_BOLD):
    fm.fontManager.addfont(PLAYFAIR_BOLD)
    TITLE_FONT = fm.FontProperties(fname=PLAYFAIR_BOLD)
else:
    TITLE_FONT = fm.FontProperties(family="serif", weight="bold")
CONTINENT_FONT = fm.FontProperties(family="Baskerville", weight="bold")
CITY_FONT = fm.FontProperties(family="Baskerville", style="italic")

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
            fontsize=14, color=ANTHRACITE, ha="center", va="center", fontproperties=CONTINENT_FONT,
        )
    for name, lon, lat in _load_city_labels():
        ax.plot(
            lon, lat, marker="o", markersize=2, color=ANTHRACITE,
            transform=ccrs.PlateCarree(), zorder=6,
        )
        ax.text(
            lon + 1, lat, name, transform=ccrs.PlateCarree(), zorder=6,
            fontsize=7.5, color=ANTHRACITE, ha="left", va="center", fontproperties=CITY_FONT,
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


def plot_h3_map(
    h3_csv_path, travel_times_csv_path, ports_csv_path, png_path, origin_iatas,
    origin_label="London", dpi=config.MAP_DPI, show_hubs=config.SHOW_HUBS, galton=False,
    band_hours=config.GALTON_BAND_HOURS, cmap_name=config.COLORMAP, labels=False,
):
    # low_memory=False: hub_id ist teils NaN (Landkacheln aus dem
    # Friction-Surface-Pfad haben keins, siehe friction_map_from_airport.py)
    # und teils String (Häfen) - pandas' Chunk-weise Typ-Erkennung warnt
    # sonst über diese gemischte Spalte, die hier ohnehin nicht genutzt wird.
    df = pd.read_csv(h3_csv_path, low_memory=False)
    covered = df[df["reisezeit_stunden"].notna()].copy()

    airports_df = pd.read_csv(travel_times_csv_path)
    origins = airports_df[airports_df["iata_code"].isin(origin_iatas)]
    ports_df = pd.read_csv(ports_csv_path)

    fig = plt.figure(figsize=(16, 9))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.Robinson())
    ax.set_global()
    ax.add_feature(cfeature.LAND, facecolor="#f0f0e8", zorder=0)
    ax.add_feature(cfeature.OCEAN, facecolor="#d9e8f5", zorder=0)
    ax.coastlines(linewidth=0.7, color=ANTHRACITE, zorder=2)

    # Wie bei Galtons Original: ab COLOR_CAP_HOURS wird der dunkelste
    # Farbton vergeben, statt die Skala linear bis zum tatsächlichen
    # Maximum (mehrere Tage Seezeit mitten im Ozean) zu strecken.
    if cmap_name == "galton":
        cmap = LinearSegmentedColormap.from_list("galton", GALTON_COLORS)
    else:
        cmap = matplotlib.colormaps[cmap_name].copy()

    if galton:
        # contourf statt Kachel-Mosaik: siehe _build_galton_grid für die
        # Begründung (H3-Nachbarschaftsmittel glättet zu lokal, um
        # Galtons handgezeichnete Bänder nachzubilden).
        lon_grid, lat_grid, galton_values = _build_galton_grid(covered)
        boundaries = np.arange(0, config.COLOR_CAP_HOURS + band_hours, band_hours)
        mappable = ax.contourf(
            lon_grid, lat_grid, galton_values, levels=boundaries, cmap=cmap, extend="max",
            transform=ccrs.PlateCarree(), zorder=1,
        )
        n_dropped = 0
    else:
        polygons = [_cell_polygon_lonlat(h) for h in covered["h3_index"]]
        keep = [p is not None for p in polygons]
        verts = [p for p in polygons if p is not None]
        values = covered["reisezeit_stunden"].to_numpy()[keep]
        n_dropped = len(polygons) - len(verts)

        norm = Normalize(vmin=0, vmax=config.COLOR_CAP_HOURS, clip=False)
        mappable = PolyCollection(
            verts, array=values, cmap=cmap, norm=norm,
            edgecolors="none", antialiased=False, transform=ccrs.PlateCarree(), zorder=1,
        )
        ax.add_collection(mappable)

    if show_hubs:
        ax.scatter(
            airports_df["lon"], airports_df["lat"], c="#ff9d00", marker="o", s=4,
            linewidths=0, transform=ccrs.PlateCarree(), zorder=3, label="Flughafen",
        )
        ax.scatter(
            ports_df["lon"], ports_df["lat"], c="#ff00c8", marker="o", s=4,
            linewidths=0, transform=ccrs.PlateCarree(), zorder=3, label="Hafen",
        )
    ax.scatter(
        origins["lon"], origins["lat"], c="red", marker="*", s=200,
        transform=ccrs.PlateCarree(), zorder=4, label=origin_label,
    )

    cbar = fig.colorbar(mappable, ax=ax, orientation="horizontal", pad=0.05, shrink=0.6, extend="max")
    cbar.set_label(f"Reisezeit ab {origin_label} (Stunden, ab {config.COLOR_CAP_HOURS}h dunkelster Ton)")

    resolution = h3.get_resolution(covered["h3_index"].iloc[0]) if len(covered) else "?"
    if galton:
        detail = f"{band_hours}h-Bänder, geglättet (Gauß-Radius {config.GALTON_SIGMA_DEG}°)"
    else:
        detail = f"{len(covered)}/{len(df)} Kacheln abgedeckt, {n_dropped} Pol-Kacheln nicht darstellbar"
    ax.set_title(
        f"Erreichbarkeit ab {origin_label} — H3-Raster Res. {resolution}, Land+See ({detail})",
        fontproperties=TITLE_FONT, fontsize=18, color=ANTHRACITE,
    )
    ax.legend(loc="lower left", markerscale=2)

    if labels:
        _draw_labels(ax)

    fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
    print(f"Karte gespeichert unter {png_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Auflösung des PNGs")
    parser.add_argument("--no-hubs", action="store_true", help="Flughafen-/Hafen-Punkte ausblenden")
    parser.add_argument(
        "--galton", action="store_true",
        help="Retro-Look: geglättete, diskrete Farbbänder statt stufenloser Skala",
    )
    parser.add_argument(
        "--band-hours", type=float, default=config.GALTON_BAND_HOURS,
        help="Bandbreite in Stunden im --galton-Modus (0-4, 4-8, ...)",
    )
    parser.add_argument("--cmap", default=config.COLORMAP, help="Name einer matplotlib-Colormap, oder 'galton' fuer eine an das Original angelehnte Palette")
    parser.add_argument(
        "--labels", action="store_true",
        help="Kontinente und wichtigste Weltstädte beschriften, wie bei Galtons Original",
    )
    args = parser.parse_args()

    plot_h3_map(
        config.OUTPUT_H3_CSV, config.OUTPUT_CSV, config.OUTPUT_PORTS_CSV,
        config.OUTPUT_H3_MAP_PNG, config.ORIGIN_AIRPORTS,
        dpi=args.dpi, show_hubs=not args.no_hubs, galton=args.galton,
        band_hours=args.band_hours, cmap_name=args.cmap, labels=args.labels,
    )
