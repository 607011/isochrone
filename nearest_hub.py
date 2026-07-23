"""Assigns each tile the shortest total travel time via a hub type.

Total time(tile) = travel time(London -> hub) + last-mile time(hub -> tile).
Minimized over ALL hubs within range by this sum - neither "nearest
hub" nor "fastest hub from London" alone is correct, since a farther
but better-connected hub can end up faster overall despite a longer
last mile, and vice versa.

A "hub" is generic here: airport for land tiles, port for water
tiles. That's why speed and the column name for the hub ID are
parameters instead of being hardwired.
"""

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

from config import EARTH_RADIUS_KM


def assign_travel_times(
    grid_df: pd.DataFrame,
    hubs_df: pd.DataFrame,
    radius_km: float,
    speed_kmh: float,
    hub_id_col: str = "iata_code",
) -> pd.DataFrame:
    # Hubs without their own travel time (e.g. unreachable ports) must be
    # removed before they can be considered as candidates: np.argmin
    # returns NaN itself when NaN is present in the array, instead of
    # ignoring it, which would otherwise poison every result as soon as
    # such a hub lies within the search radius.
    hubs_df = hubs_df[hubs_df["reisezeit_stunden"].notna()].reset_index(drop=True)

    hub_coords_rad = np.radians(hubs_df[["lat", "lon"]].to_numpy())
    tree = BallTree(hub_coords_rad, metric="haversine")

    cell_coords_rad = np.radians(grid_df[["lat", "lon"]].to_numpy())
    radius_rad = radius_km / EARTH_RADIUS_KM
    neighbor_indices, neighbor_dist_rad = tree.query_radius(
        cell_coords_rad, r=radius_rad, return_distance=True
    )

    hub_hours = hubs_df["reisezeit_stunden"].to_numpy()
    hub_ids = hubs_df[hub_id_col].to_numpy()

    n = len(grid_df)
    best_total_hours = np.full(n, np.nan)
    best_leg_hours = np.full(n, np.nan)
    best_hub_id = np.full(n, None, dtype=object)
    num_candidates = np.zeros(n, dtype=int)

    for i, (idx, dist_rad) in enumerate(zip(neighbor_indices, neighbor_dist_rad)):
        if len(idx) == 0:
            continue
        leg_km = dist_rad * EARTH_RADIUS_KM
        leg_hours = leg_km / speed_kmh
        total_hours = hub_hours[idx] + leg_hours

        best = np.argmin(total_hours)
        best_total_hours[i] = total_hours[best]
        best_leg_hours[i] = leg_hours[best]
        best_hub_id[i] = hub_ids[idx][best]
        num_candidates[i] = len(idx)

    result = grid_df.copy()
    result["reisezeit_stunden"] = best_total_hours
    result["letzte_meile_stunden"] = best_leg_hours
    result["hub_id"] = best_hub_id
    result["num_hubs_in_radius"] = num_candidates
    return result


def nearest_value(points_df: pd.DataFrame, reference_df: pd.DataFrame, value_col: str) -> np.ndarray:
    """Value of the nearest tile in reference_df, for each point in points_df.

    No dedicated hub mechanism - pure nearest-neighbor search. Used e.g.
    to simply give ports the travel time of their nearest land tile,
    instead of computing it separately via their own airport search.
    """
    reference_df = reference_df[reference_df[value_col].notna()].reset_index(drop=True)
    reference_coords_rad = np.radians(reference_df[["lat", "lon"]].to_numpy())
    tree = BallTree(reference_coords_rad, metric="haversine")

    point_coords_rad = np.radians(points_df[["lat", "lon"]].to_numpy())
    _, nearest_idx = tree.query(point_coords_rad, k=1)
    return reference_df[value_col].to_numpy()[nearest_idx.ravel()]
