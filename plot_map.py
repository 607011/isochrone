"""Punktkarte: Flughäfen eingefärbt nach Reisezeit ab London.

Reiner Zwischenschritt vor den Isochronen-Konturlinien, um die
räumliche Verteilung und Dichte der erreichten Flughäfen zu sehen -
vor allem, wo Konturen später sinnvoll (viele Stützpunkte) bzw.
irreführend (leere Ozean-/Wüstenflächen) wären.
"""

import os

# certifi statt der (auf manchen macOS-Python-Installationen kaputten)
# System-CA-Kette verwenden, sonst schlägt Cartopys Küstenlinien-Download fehl.
if "SSL_CERT_FILE" not in os.environ:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import pandas as pd

import config


def plot_travel_times(csv_path, png_path, origin_iatas):
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
    cbar.set_label("Reisezeit ab London (Stunden)")

    ax.set_title(f"Erreichbarkeit ab London — {len(df)} Flughäfen (Stand: OpenFlights-Routennetz ~2014)")
    ax.legend(loc="lower left")

    fig.savefig(png_path, dpi=150, bbox_inches="tight")
    print(f"Karte gespeichert unter {png_path}")


if __name__ == "__main__":
    plot_travel_times(config.OUTPUT_CSV, config.OUTPUT_MAP_PNG, config.ORIGIN_AIRPORTS)
