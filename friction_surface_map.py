"""Baut aus dem globalen Friction-Surface-Ergebnis (friction_surface_global.py)
eine H3-Karte und stellt sie neben die bisherige isotrope Karte.

Nur Landkacheln bekommen den neuen, straßenbasierten Wert - Wasserkacheln
kommen unverändert aus main_h3.py (dessen Häfen-Modell ist unabhängig
vom Friction-Surface-Raster, siehe friction_surface_global.py). Bei einer
anderen als der Standard-Auflösung muss main_h3.py -r <auflösung> vorher
gelaufen sein, damit die Wasserkacheln zur gewählten Auflösung passen.
"""

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

import config
from h3_grid import build_grid
from land_mask import is_land
from main_h3 import _output_path_for
from plot_h3_map import plot_h3_map

TRAVEL_MINUTES_NPY = "friction_data/land_travel_minutes.npy"
NODE_LATLON_NPY = "friction_data/land_node_latlon.npy"

OUTPUT_CSV = "h3_travel_times_london_friction_surface.csv"
OUTPUT_PNG = "h3_travel_times_map_london_friction_surface_land.png"


def main(
    resolution=config.H3_RESOLUTION, dpi=config.MAP_DPI, show_hubs=config.SHOW_HUBS, galton=False,
    band_hours=config.GALTON_BAND_HOURS, cmap_name=config.COLORMAP, labels=False, robinson=False,
):
    minutes = np.load(TRAVEL_MINUTES_NPY)
    node_latlon = np.load(NODE_LATLON_NPY)
    finite = np.isfinite(minutes)
    tree = BallTree(np.radians(node_latlon[finite]), metric="haversine")

    grid_df = build_grid(resolution)
    on_land = is_land(grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy())
    land_df = grid_df[on_land].reset_index(drop=True)

    _, idx = tree.query(np.radians(land_df[["lat", "lon"]].to_numpy()), k=1)
    land_df["reisezeit_stunden"] = minutes[finite][idx.ravel()] / 60

    h3_csv_in = _output_path_for(config.OUTPUT_H3_CSV, resolution)
    h3_df = pd.read_csv(h3_csv_in)
    sea_df = h3_df[h3_df["hub_type"] == "port"][["h3_index", "lat", "lon", "reisezeit_stunden"]]

    combined = pd.concat([land_df[["h3_index", "lat", "lon", "reisezeit_stunden"]], sea_df], ignore_index=True)

    res_suffix = "" if resolution == config.H3_RESOLUTION else f"_res{resolution}"
    galton_suffix = "_galton" if galton else ""
    labels_suffix = "_labels" if labels else ""
    proj_suffix = "_robinson" if robinson else ""
    output_csv = OUTPUT_CSV.replace(".csv", f"{res_suffix}.csv")
    output_png = OUTPUT_PNG.replace(".png", f"{res_suffix}{galton_suffix}{labels_suffix}{proj_suffix}.png")
    combined.to_csv(output_csv, index=False)

    covered = combined["reisezeit_stunden"].notna().sum()
    print(f"{covered} von {len(combined)} Kacheln abgedeckt "
          f"(Land via Friction Surface: {land_df['reisezeit_stunden'].notna().sum()}/{len(land_df)}).")

    ports_csv_in = _output_path_for(config.OUTPUT_PORTS_CSV, resolution)
    plot_h3_map(
        output_csv, config.OUTPUT_CSV, ports_csv_in, output_png, config.ORIGIN_AIRPORTS,
        dpi=dpi, show_hubs=show_hubs, galton=galton, band_hours=band_hours, cmap_name=cmap_name,
        labels=labels, robinson=robinson,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-r", "--resolution", type=int, default=config.H3_RESOLUTION, help="H3-Auflösung (0-15)")
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
    parser.add_argument(
        "--robinson", action="store_true",
        help="Robinson-Projektion statt der (seit Galtons Original) Standard-Mercator-Projektion",
    )
    args = parser.parse_args()

    main(
        resolution=args.resolution, dpi=args.dpi, show_hubs=not args.no_hubs, galton=args.galton,
        band_hours=args.band_hours, cmap_name=args.cmap, labels=args.labels, robinson=args.robinson,
    )
