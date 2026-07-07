"""Ordnet jeder Kachel die kürzeste Gesamtreisezeit über einen Hub-Typ zu.

Gesamtzeit(Kachel) = Reisezeit(London -> Hub) + Letzte-Meile-Zeit(Hub -> Kachel).
Minimiert wird über ALLE Hubs im Radius nach dieser Summe - weder "nächster
Hub" noch "schnellster Hub ab London" allein sind korrekt, denn ein weiter
entfernter, aber besser angebundener Hub kann trotz längerer letzter Meile
insgesamt schneller sein, und umgekehrt.

Ein "Hub" ist hier generisch: Flughafen für Landkacheln, Hafen für
Wasserkacheln. Deshalb sind Geschwindigkeit und Spaltenname für die
Hub-ID Parameter statt fest verdrahtet zu sein.
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
    # Hubs ohne eigene Reisezeit (z.B. unerreichbare Häfen) muessen raus,
    # bevor sie als Kandidaten in Frage kommen: np.argmin gibt bei NaN im
    # Array selbst NaN zurueck, statt es zu ignorieren, und würde sonst
    # jedes Ergebnis vergiften, sobald ein solcher Hub im Suchradius liegt.
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
    """Wert der nächstgelegenen Kachel in reference_df, für jeden Punkt in points_df.

    Kein eigener Hub-Mechanismus - reine Nachbarschaftssuche. Genutzt z.B.
    dafür, Häfen einfach die Reisezeit ihrer nächstgelegenen Landkachel zu
    geben, statt sie separat über eine eigene Flughafen-Suche zu berechnen.
    """
    reference_df = reference_df[reference_df[value_col].notna()].reset_index(drop=True)
    reference_coords_rad = np.radians(reference_df[["lat", "lon"]].to_numpy())
    tree = BallTree(reference_coords_rad, metric="haversine")

    point_coords_rad = np.radians(points_df[["lat", "lon"]].to_numpy())
    _, nearest_idx = tree.query(point_coords_rad, k=1)
    return reference_df[value_col].to_numpy()[nearest_idx.ravel()]
