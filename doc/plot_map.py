"""Point map: airports colored by travel time from London.

Purely an intermediate step before the isochrone contour lines, to see
the spatial distribution and density of reached airports - especially
where contours would later make sense (many support points) vs. be
misleading (empty ocean/desert areas).
"""

import os

# Use certifi instead of the system CA chain (broken on some macOS
# Python installations), otherwise Cartopy's coastline download fails.
if "SSL_CERT_FILE" not in os.environ:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import pandas as pd

# Moved to doc/ (standalone example script, not part of the web
# backend's dependency chain) - the modules below still live in the
# project root, so it needs to be on sys.path regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


def plot_travel_times(csv_path, png_path, origin_iatas, dpi=config.MAP_DPI):
    df = pd.read_csv(csv_path)

    fig = plt.figure(figsize=(16, 9))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.Robinson())
    ax.set_global()
    ax.add_feature(cfeature.LAND, facecolor="#f0f0e8")
    ax.add_feature(cfeature.OCEAN, facecolor="#d9e8f5")
    ax.coastlines(linewidth=0.5, color="#888888")

    is_origin = df["iata_code"].isin(origin_iatas)

    sc = ax.scatter(
        df.loc[~is_origin, "lon"], df.loc[~is_origin, "lat"],
        c=df.loc[~is_origin, "reisezeit_stunden"],
        cmap=config.COLORMAP,
        s=8, alpha=0.85, linewidths=0,
        transform=ccrs.PlateCarree(),
        zorder=3,
    )
    ax.scatter(
        df.loc[is_origin, "lon"], df.loc[is_origin, "lat"],
        c="red", marker="*", s=200,
        transform=ccrs.PlateCarree(),
        zorder=4, label="London",
    )

    cbar = fig.colorbar(sc, ax=ax, orientation="horizontal", pad=0.05, shrink=0.6)
    cbar.set_label("Travel time from London (hours)")

    ax.set_title(f"Reachability from London — {len(df)} airports (as of OpenFlights route network ~2014)")
    ax.legend(loc="lower left")

    fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
    print(f"Map saved to {png_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Resolution of the PNG")
    args = parser.parse_args()

    plot_travel_times(config.OUTPUT_CSV, config.OUTPUT_MAP_PNG, config.ORIGIN_AIRPORTS, dpi=args.dpi)
