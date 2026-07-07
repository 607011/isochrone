"""Baut aus dem globalen Friction-Surface-Ergebnis (friction_surface_global.py)
eine H3-Karte und stellt sie neben die bisherige isotrope Karte.

Nur Landkacheln bekommen den neuen, straßenbasierten Wert - Wasserkacheln
bleiben unverändert aus main_h3.py (dessen Häfen-Modell ist unabhängig
vom Friction-Surface-Raster, siehe friction_surface_global.py).
"""

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

import config
from h3_grid import build_grid
from land_mask import is_land
from plot_h3_map import plot_h3_map

TRAVEL_MINUTES_NPY = "friction_data/land_travel_minutes.npy"
NODE_LATLON_NPY = "friction_data/land_node_latlon.npy"

OUTPUT_CSV = "h3_travel_times_london_friction_surface.csv"
OUTPUT_PNG = "h3_travel_times_map_london_friction_surface_land.png"


def main():
    minutes = np.load(TRAVEL_MINUTES_NPY)
    node_latlon = np.load(NODE_LATLON_NPY)
    finite = np.isfinite(minutes)
    tree = BallTree(np.radians(node_latlon[finite]), metric="haversine")

    grid_df = build_grid(config.H3_RESOLUTION)
    on_land = is_land(grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy())
    land_df = grid_df[on_land].reset_index(drop=True)

    _, idx = tree.query(np.radians(land_df[["lat", "lon"]].to_numpy()), k=1)
    land_df["reisezeit_stunden"] = minutes[finite][idx.ravel()] / 60

    h3_df = pd.read_csv(config.OUTPUT_H3_CSV)
    sea_df = h3_df[h3_df["hub_type"] == "port"][["h3_index", "lat", "lon", "reisezeit_stunden"]]

    combined = pd.concat([land_df[["h3_index", "lat", "lon", "reisezeit_stunden"]], sea_df], ignore_index=True)
    combined.to_csv(OUTPUT_CSV, index=False)

    covered = combined["reisezeit_stunden"].notna().sum()
    print(f"{covered} von {len(combined)} Kacheln abgedeckt "
          f"(Land via Friction Surface: {land_df['reisezeit_stunden'].notna().sum()}/{len(land_df)}).")

    plot_h3_map(OUTPUT_CSV, config.OUTPUT_CSV, config.OUTPUT_PORTS_CSV, OUTPUT_PNG, config.ORIGIN_AIRPORTS)


if __name__ == "__main__":
    main()
