"""Friction-Surface-Erreichbarkeitskarte ab einem beliebigen Flughafen.

Kombiniert map_from_airport.py (beliebiger Start-Flughafen) mit
friction_surface_global.py (anisotrope Bodenzeit via Kostendistanz über
das MAP-Friction-Raster statt isotropem Kreismodell). Der Rastergraph
selbst hängt nicht vom Start ab und wird aus dem Cache von
friction_surface_global.py wiederverwendet (muss also einmal vorher
gelaufen sein) - nur der virtuelle Superknoten bekommt neue Gewichte
(die Reisezeiten des neuen Start-Flughafens ab sich selbst), und Dijkstra
läuft erneut (unter einer Sekunde).
"""

import sys

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

import config
import friction_surface_global as friction
from h3_grid import build_grid
from land_mask import is_land
from map_from_airport import build_sea, build_travel_times, slug_for
from plot_h3_map import plot_h3_map


def build_friction_land(travel_times_df, graph, node_lat, node_lon, minutes_path):
    minutes = friction.run_dijkstra(graph, node_lat, node_lon, travel_times_df, output_path=minutes_path)
    finite = np.isfinite(minutes)
    tree = BallTree(np.radians(np.column_stack([node_lat[finite], node_lon[finite]])), metric="haversine")

    grid_df = build_grid(config.H3_RESOLUTION)
    on_land = is_land(grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy())
    land_df = grid_df[on_land].reset_index(drop=True)

    _, idx = tree.query(np.radians(land_df[["lat", "lon"]].to_numpy()), k=1)
    land_df["reisezeit_stunden"] = minutes[finite][idx.ravel()] / 60
    land_df["hub_type"] = "airport"
    return land_df


def main(origin_iata):
    travel_times_df = build_travel_times([origin_iata])
    if origin_iata not in travel_times_df["iata_code"].values:
        raise ValueError(f"{origin_iata} ist im Flugnetz nicht erreichbar/vorhanden.")

    origin_row = travel_times_df[travel_times_df["iata_code"] == origin_iata].iloc[0]
    slug = slug_for(origin_iata, origin_row["name"])

    graph, node_lat, node_lon = friction.load_graph()
    land_result = build_friction_land(
        travel_times_df, graph, node_lat, node_lon,
        minutes_path=f"friction_data/land_travel_minutes_from_{slug}.npy",
    )
    sea_result, ports_df = build_sea(land_result)
    h3_df = pd.concat([land_result, sea_result], ignore_index=True)

    travel_times_csv = f"travel_times_from_{slug}.csv"
    h3_csv = f"h3_travel_times_from_{slug}_friction_surface.csv"
    ports_csv = f"ports_travel_times_from_{slug}_friction_surface.csv"
    png = f"h3_travel_times_map_from_{slug}_friction_surface.png"

    travel_times_df.to_csv(travel_times_csv, index=False)
    h3_df.to_csv(h3_csv, index=False)
    ports_df.to_csv(ports_csv, index=False)

    plot_h3_map(h3_csv, travel_times_csv, ports_csv, png, [origin_iata], origin_label=origin_row["name"])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "THU")
