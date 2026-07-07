"""Globale anisotrope Bodenzeit über das MAP-Friction-Surface-Raster.

Ersetzt für Landkacheln das isotrope GROUND_SPEED_KMH-Kreismodell durch
eine echte Kostendistanz-Berechnung über ein globales Geländereibungs-
Raster (Malaria Atlas Project / Weiss et al., "2020 motorized friction
surface", 1 km Auflösung, Minuten pro Meter). Siehe friction_surface_demo.py
für die kleinräumige Variante mit echtem OSM-Straßennetz (Birdsville) -
dieses Skript ist das globale Gegenstück, aber mit einem vorgerechneten
Reibungs-Raster statt Live-Routing, weil Live-Routing weltweit
unverhältnismäßig aufwändig wäre (siehe MEMO.md).

Das Raster hat auch über offenem Ozean gültige (langsame) Werte, vermutlich
für Boots-/Fährverbindungen gedacht - das würde mit dem bestehenden
See-Modell (main_h3.py, über Häfen) kollidieren. Deshalb wird auf reines
Land maskiert (global-land-mask, wie im Rest des Projekts), Wasserpixel
werden aus dem Graphen entfernt statt als langsame Kanten zugelassen.

Rechnet in drei Phasen, jede für sich cachebar:
1. Raster laden, auf ~11 km Auflösung herunterrechnen (Min-Pooling, damit
   dünne schnelle Straßen bei der Vergröberung nicht verschwinden).
2. Daraus einen Graphen nur über Landpixeln bauen (8er-Nachbarschaft,
   Kantengewicht = Reibung * echte Distanz in Metern).
3. Von einem virtuellen Superknoten aus, der mit jedem Flughafen-Pixel
   über eine Kante mit Gewicht = dessen eigene Reisezeit ab London
   verbunden ist, einmal global Dijkstra rechnen (scipy) - liefert direkt
   Flugzeit + echte (anisotrope) Bodenzeit kombiniert, exakt das gleiche
   Prinzip wie der virtuelle Ursprungsknoten in travel_time.py/nearest_hub.py,
   nur über ein Rasterraster statt einer Radius-Suche.
"""

import time

import numpy as np
import pandas as pd
import rasterio
from global_land_mask import globe
from scipy import sparse
from scipy.sparse.csgraph import dijkstra
from sklearn.neighbors import BallTree

import config

FRICTION_TIF = "friction_data/2020_motorized_friction_surface.geotiff"
DOWNSAMPLE_FACTOR = 12  # ~1km -> ~11km Pixelkantenlänge
PIXEL_DEG = 0.008333333333333333 * DOWNSAMPLE_FACTOR

CACHE_FRICTION = "friction_data/friction_downsampled_min.npy"
CACHE_GRAPH = "friction_data/land_graph.npz"
CACHE_NODE_LATLON = "friction_data/land_node_latlon.npy"
CACHE_TRAVEL_MINUTES = "friction_data/land_travel_minutes.npy"


def downsample_friction():
    t0 = time.time()
    with rasterio.open(FRICTION_TIF) as src:
        data = src.read(1)
        nodata = src.nodata
    h, w = data.shape
    factor = DOWNSAMPLE_FACTOR
    masked = np.where(data == nodata, np.inf, data)
    blocks = masked.reshape(h // factor, factor, w // factor, factor)
    down = blocks.min(axis=(1, 3))
    down = np.where(np.isinf(down), np.nan, down)
    np.save(CACHE_FRICTION, down.astype(np.float32))
    print(f"Raster heruntergerechnet auf {down.shape} in {time.time()-t0:.0f}s")
    return down


def build_land_graph(friction):
    h, w = friction.shape
    lat = 85 - PIXEL_DEG * (np.arange(h) + 0.5)
    lon = -180 + PIXEL_DEG * (np.arange(w) + 0.5)
    lon_grid, lat_grid = np.meshgrid(lon, lat)

    is_land = globe.is_land(lat_grid, lon_grid) & ~np.isnan(friction)
    print(f"{is_land.sum()} Landpixel von {is_land.size}.")

    node_id = np.full((h, w), -1, dtype=np.int64)
    node_id[is_land] = np.arange(is_land.sum())
    node_lat = lat_grid[is_land]
    node_lon = lon_grid[is_land]

    lat_step_km = config.EARTH_RADIUS_KM * np.radians(PIXEL_DEG)

    # Kanten nur über explizites Slicing bauen (kein np.roll!) - roll
    # umschließt am Rand auf die gegenüberliegende Kartenseite, was bei
    # einer Vorzeichen-Verwechslung still falsche Kanten erzeugt, statt
    # sauber zu crashen. Kostet dafür Kanten über den Antimeridian (~180°
    # Länge) - kleine, akzeptierte Lücke, siehe MEMO.md.
    rows, cols, weights = [], [], []
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di == 0 and dj == 0:
                continue
            lo_i, hi_i = max(0, -di), h - max(0, di)
            lo_j, hi_j = max(0, -dj), w - max(0, dj)

            src_land = is_land[lo_i:hi_i, lo_j:hi_j]
            dst_land = is_land[lo_i + di:hi_i + di, lo_j + dj:hi_j + dj]
            valid = src_land & dst_land

            src_idx = node_id[lo_i:hi_i, lo_j:hi_j][valid]
            dst_idx = node_id[lo_i + di:hi_i + di, lo_j + dj:hi_j + dj][valid]

            src_fric = friction[lo_i:hi_i, lo_j:hi_j][valid]
            dst_fric = friction[lo_i + di:hi_i + di, lo_j + dj:hi_j + dj][valid]
            avg_friction = 0.5 * (src_fric + dst_fric)

            src_lat = lat_grid[lo_i:hi_i, lo_j:hi_j][valid]
            dlon_km = abs(dj) * lat_step_km * np.cos(np.radians(src_lat))
            dlat_km = abs(di) * lat_step_km
            dist_m = np.sqrt(dlat_km ** 2 + dlon_km ** 2) * 1000

            rows.append(src_idx)
            cols.append(dst_idx)
            weights.append(avg_friction * dist_m)

    rows = np.concatenate(rows)
    cols = np.concatenate(cols)
    weights = np.concatenate(weights)
    n = int(is_land.sum())
    graph = sparse.csr_matrix((weights, (rows, cols)), shape=(n, n))
    sparse.save_npz(CACHE_GRAPH, graph)
    np.save(CACHE_NODE_LATLON, np.column_stack([node_lat, node_lon]).astype(np.float32))
    print(f"Graph gebaut: {n} Knoten, {graph.nnz} Kanten.")
    return graph, node_lat, node_lon


def run_dijkstra(graph, node_lat, node_lon, airports_df):
    n = graph.shape[0]
    tree = BallTree(np.radians(np.column_stack([node_lat, node_lon])), metric="haversine")
    _, airport_node_idx = tree.query(np.radians(airports_df[["lat", "lon"]].to_numpy()), k=1)
    airport_node_idx = airport_node_idx.ravel()

    # virtueller Superknoten (Index n) -> Flughafen-Pixel, Kantengewicht =
    # eigene Reisezeit des Flughafens ab London, in Minuten.
    graph_coo = graph.tocoo()
    virtual_rows = np.full(len(airports_df), n)
    virtual_cols = airport_node_idx
    virtual_weights = airports_df["reisezeit_stunden"].to_numpy() * 60

    all_rows = np.concatenate([graph_coo.row, virtual_rows])
    all_cols = np.concatenate([graph_coo.col, virtual_cols])
    all_data = np.concatenate([graph_coo.data, virtual_weights])
    big = sparse.csr_matrix((all_data, (all_rows, all_cols)), shape=(n + 1, n + 1))

    t0 = time.time()
    dist = dijkstra(big, directed=True, indices=[n])[0]
    print(f"Dijkstra fertig in {time.time()-t0:.0f}s")
    minutes = dist[:n]
    np.save(CACHE_TRAVEL_MINUTES, minutes.astype(np.float32))
    return minutes


def main():
    airports_df = pd.read_csv(config.OUTPUT_CSV)

    friction = downsample_friction()
    graph, node_lat, node_lon = build_land_graph(friction)
    run_dijkstra(graph, node_lat, node_lon, airports_df)


if __name__ == "__main__":
    main()
