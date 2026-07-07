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
from matplotlib.collections import PolyCollection
from matplotlib.colors import Normalize
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import pandas as pd

import config

# Kacheln, deren Eckpunkte-Längengrade (unkorrigiert) mehr als das hier
# überspannen, liegen an einem Pol - dort laufen alle Längengrade
# zusammen, das ist keine Antimeridian-Überquerung. Die "+360"-Korrektur
# für echte Antimeridian-Fälle würde solche Kacheln zu einem absurd
# breiten Riesenpolygon aufblähen, das große Teile der Karte verdeckt.
POLE_DEGENERACY_THRESHOLD_DEG = 300


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


def plot_h3_map(
    h3_csv_path, travel_times_csv_path, ports_csv_path, png_path, origin_iatas,
    origin_label="London", dpi=config.MAP_DPI, show_hubs=config.SHOW_HUBS,
):
    df = pd.read_csv(h3_csv_path)
    covered = df[df["reisezeit_stunden"].notna()].copy()

    airports_df = pd.read_csv(travel_times_csv_path)
    origins = airports_df[airports_df["iata_code"].isin(origin_iatas)]
    ports_df = pd.read_csv(ports_csv_path)

    fig = plt.figure(figsize=(16, 9))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.Robinson())
    ax.set_global()
    ax.add_feature(cfeature.LAND, facecolor="#f0f0e8", zorder=0)
    ax.add_feature(cfeature.OCEAN, facecolor="#d9e8f5", zorder=0)
    ax.coastlines(linewidth=0.5, color="#888888", zorder=2)

    polygons = [_cell_polygon_lonlat(h) for h in covered["h3_index"]]
    keep = [p is not None for p in polygons]
    verts = [p for p in polygons if p is not None]
    values = covered["reisezeit_stunden"].to_numpy()[keep]
    n_dropped = len(polygons) - len(verts)

    # Wie bei Galtons Original: ab COLOR_CAP_HOURS wird der dunkelste
    # Farbton vergeben, statt die Skala linear bis zum tatsächlichen
    # Maximum (mehrere Tage Seezeit mitten im Ozean) zu strecken.
    cmap = matplotlib.colormaps[config.COLORMAP].copy()
    norm = Normalize(vmin=0, vmax=config.COLOR_CAP_HOURS, clip=False)

    coll = PolyCollection(
        verts, array=values, cmap=cmap, norm=norm,
        edgecolors="none", antialiased=False, transform=ccrs.PlateCarree(), zorder=1,
    )
    ax.add_collection(coll)

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

    cbar = fig.colorbar(coll, ax=ax, orientation="horizontal", pad=0.05, shrink=0.6, extend="max")
    cbar.set_label(f"Reisezeit ab {origin_label} (Stunden, ab {config.COLOR_CAP_HOURS}h dunkelster Ton)")

    resolution = h3.get_resolution(covered["h3_index"].iloc[0]) if len(covered) else "?"
    ax.set_title(
        f"Erreichbarkeit ab {origin_label} — H3-Raster Res. {resolution}, "
        f"Land+See ({len(covered)}/{len(df)} Kacheln abgedeckt, "
        f"{n_dropped} Pol-Kacheln nicht darstellbar)"
    )
    ax.legend(loc="lower left", markerscale=2)

    fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
    print(f"Karte gespeichert unter {png_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Auflösung des PNGs")
    parser.add_argument("--no-hubs", action="store_true", help="Flughafen-/Hafen-Punkte ausblenden")
    args = parser.parse_args()

    plot_h3_map(
        config.OUTPUT_H3_CSV, config.OUTPUT_CSV, config.OUTPUT_PORTS_CSV,
        config.OUTPUT_H3_MAP_PNG, config.ORIGIN_AIRPORTS,
        dpi=args.dpi, show_hubs=not args.no_hubs,
    )
