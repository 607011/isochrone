"""Regional comparison: isotropic ground time vs. real road network (Birdsville).

main_h3.py assumes a flat speed over the straight-line distance for
the "last mile" airport->tile (GROUND_SPEED_KMH, isotropic - see
config.py). That's a rough simplification: you don't just "stumble" out
of the airport and then drive equally fast in every direction, you
follow roads (cf. the historical Melbourne reachability map that
brought the user to this question).

This script computes that for the region around Birdsville Airport
(BVI) - one of the most remote airports in the dataset - once with the
real road network (OpenStreetMap extract for Queensland, travel times
per road class) instead of the circular isotropy, and shows both
variants side by side. Deliberately regional only, not global - see
MEMO.md for the trade-off (real routing worldwide would be
disproportionately expensive; the effect's impact already shows up in
a single region).
"""

import os
import sys
from pathlib import Path

if "SSL_CERT_FILE" not in os.environ:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()

import geopandas as gpd
import h3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import Normalize
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import networkx as nx
import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

# Moved to doc/ (standalone example script, not part of the web
# backend's dependency chain) - the modules below still live in the
# project root, so it needs to be on sys.path regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from distance import haversine_miles


def _haversine_km_vec(lat1, lon1, lat2, lon2):
    lat1_r, lon1_r, lat2_r, lon2_r = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    return 2 * config.EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))

AIRPORT_IATA = "BVI"
AIRPORT_NAME = "Birdsville Airport"
AIRPORT_LAT, AIRPORT_LON = -25.8975, 139.348
AIRPORT_OWN_TRAVEL_HOURS = 31.69  # from travel_times.csv (5 transfers from London)

EDGES_PATH = "osm_data/birdsville_edges.parquet"
NODES_PATH = "osm_data/birdsville_nodes.parquet"

H3_RESOLUTION = 6  # finer than the global map (res. 4), to make the road layout visible
REGION_HALF_WIDTH_DEG = 3.0

# Rough default speeds per road class (km/h) - most OSM ways in the
# outback have no maxspeed tag.
DEFAULT_SPEED_KMH = {
    "motorway": 110, "trunk": 100, "primary": 100, "secondary": 90,
    "tertiary": 80, "tertiary_link": 60, "unclassified": 60,
    "residential": 50, "service": 20, "rest_area": 10, "living_street": 20,
}
FALLBACK_SPEED_KMH = 50


def _speed_for(highway):
    if isinstance(highway, list):
        highway = highway[0] if highway else None
    return DEFAULT_SPEED_KMH.get(highway, FALLBACK_SPEED_KMH)


def build_road_graph():
    edges = gpd.read_parquet(EDGES_PATH)
    nodes = gpd.read_parquet(NODES_PATH).set_index("id")

    G = nx.Graph()
    for node_id, row in nodes.iterrows():
        G.add_node(node_id, lat=row["lat"], lon=row["lon"])

    for _, row in edges.iterrows():
        speed_kmh = _speed_for(row["highway"])
        hours = (row["length"] / 1000) / speed_kmh
        G.add_edge(row["u"], row["v"], hours=hours)

    return G, nodes


def nearest_node(nodes_df, lat, lon):
    tree = BallTree(np.radians(nodes_df[["lat", "lon"]].to_numpy()), metric="haversine")
    _, idx = tree.query(np.radians([[lat, lon]]), k=1)
    return nodes_df.index[idx.ravel()[0]]


def build_region_grid(center_lat, center_lon, half_width_deg, resolution):
    cells = h3.grid_disk(h3.latlng_to_cell(center_lat, center_lon, resolution), 200)
    rows = []
    for cell in cells:
        lat, lon = h3.cell_to_latlng(cell)
        if abs(lat - center_lat) <= half_width_deg and abs(lon - center_lon) <= half_width_deg:
            rows.append({"h3_index": cell, "lat": lat, "lon": lon})
    return pd.DataFrame(rows)


def main():
    print("Building road graph...")
    G, nodes_df = build_road_graph()
    print(f"{G.number_of_nodes()} nodes, {G.number_of_edges()} edges.")

    origin_node = nearest_node(nodes_df, AIRPORT_LAT, AIRPORT_LON)
    road_hours = nx.single_source_dijkstra_path_length(G, origin_node, weight="hours")
    print(f"{len(road_hours)} nodes reachable from {AIRPORT_NAME} via the road network.")

    reachable_nodes = nodes_df.loc[list(road_hours.keys())]
    reachable_tree = BallTree(np.radians(reachable_nodes[["lat", "lon"]].to_numpy()), metric="haversine")
    reachable_hours = np.array([road_hours[n] for n in reachable_nodes.index])

    grid_df = build_region_grid(AIRPORT_LAT, AIRPORT_LON, REGION_HALF_WIDTH_DEG, H3_RESOLUTION)
    print(f"{len(grid_df)} H3 tiles (res. {H3_RESOLUTION}) in the region.")

    _, idx = reachable_tree.query(np.radians(grid_df[["lat", "lon"]].to_numpy()), k=1)
    nearest_hours = reachable_hours[idx.ravel()]
    nearest_node_dist_km = np.array([
        haversine_miles(lat, lon, reachable_nodes.iloc[i]["lat"], reachable_nodes.iloc[i]["lon"]) * 1.60934
        for (lat, lon), i in zip(grid_df[["lat", "lon"]].to_numpy(), idx.ravel())
    ])
    # add the last, short stretch from the tile center to the nearest
    # captured road point isotropically too, otherwise the road network
    # looks "too perfect"
    snap_hours = nearest_node_dist_km / config.GROUND_SPEED_KMH
    grid_df["ground_hours_road"] = nearest_hours + snap_hours

    dist_km = _haversine_km_vec(AIRPORT_LAT, AIRPORT_LON, grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy())
    grid_df["ground_hours_isotropic"] = dist_km / config.GROUND_SPEED_KMH

    vmax = max(grid_df["ground_hours_road"].quantile(0.98), grid_df["ground_hours_isotropic"].quantile(0.98))

    fig, axes = plt.subplots(
        1, 2, figsize=(16, 8),
        subplot_kw={"projection": ccrs.PlateCarree()},
    )
    extent = [
        AIRPORT_LON - REGION_HALF_WIDTH_DEG, AIRPORT_LON + REGION_HALF_WIDTH_DEG,
        AIRPORT_LAT - REGION_HALF_WIDTH_DEG, AIRPORT_LAT + REGION_HALF_WIDTH_DEG,
    ]
    cmap = matplotlib.colormaps[config.COLORMAP]
    norm = Normalize(vmin=0, vmax=vmax)

    edges_gdf = gpd.read_parquet(EDGES_PATH)
    road_segments = [list(geom.coords) for geom in edges_gdf.geometry if geom is not None]

    for ax, col, title in [
        (axes[0], "ground_hours_isotropic", "Isotropic (straight-line / 80 km/h)"),
        (axes[1], "ground_hours_road", "Road network (OpenStreetMap)"),
    ]:
        ax.set_extent(extent, crs=ccrs.PlateCarree())
        ax.add_feature(cfeature.LAND, facecolor="#f0f0e8", zorder=0)
        ax.add_feature(cfeature.OCEAN, facecolor="#d9e8f5", zorder=0)

        verts = [h3.cell_to_boundary(h) for h in grid_df["h3_index"]]
        verts = [[(lon, lat) for lat, lon in v] for v in verts]
        coll = PolyCollection(
            verts, array=grid_df[col].to_numpy(), cmap=cmap, norm=norm,
            edgecolors="none", antialiased=False, transform=ccrs.PlateCarree(), zorder=1,
        )
        ax.add_collection(coll)

        if col == "ground_hours_road":
            lc = LineCollection(road_segments, colors="#444444", linewidths=0.3, alpha=0.6, zorder=2,
                                 transform=ccrs.PlateCarree())
            ax.add_collection(lc)

        ax.scatter(
            [AIRPORT_LON], [AIRPORT_LAT], c="red", marker="*", s=250,
            transform=ccrs.PlateCarree(), zorder=4,
        )
        ax.set_title(title)

    cbar = fig.colorbar(
        matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap),
        ax=axes, orientation="horizontal", pad=0.05, shrink=0.6,
    )
    cbar.set_label("Ground time from Birdsville Airport (hours)")

    fig.suptitle(
        f"{AIRPORT_NAME}: isotropic vs. road-based ground-time modeling "
        f"(H3 res. {H3_RESOLUTION}, {REGION_HALF_WIDTH_DEG*2}° region)"
    )

    out_path = "doc/birdsville_friction_surface_vs_isotropic.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Map saved to {out_path}")


if __name__ == "__main__":
    main()
