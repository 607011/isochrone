"""Regionaler Vergleich: isotrope Bodenzeit vs. echtes Straßennetz (Birdsville).

main_h3.py nimmt für die "letzte Meile" Flughafen->Kachel eine flache
Geschwindigkeit über die Luftlinie an (GROUND_SPEED_KMH, isotrop - siehe
config.py). Das ist eine grobe Vereinfachung: man "stolpert" ja nicht aus
dem Flughafen und fährt dann in jede Richtung gleich schnell, sondern
folgt Straßen (vgl. die historische Melbourne-Erreichbarkeitskarte, die
den Nutzer zu dieser Frage gebracht hat).

Dieses Skript rechnet das für die Region um Birdsville Airport (BVI) -
einen der entlegensten Flughäfen im Datensatz - einmal mit dem echten
Straßennetz (OpenStreetMap-Auszug für Queensland, Fahrzeiten je
Straßenklasse) statt der Kreis-Isotropie durch und stellt beide Varianten
nebeneinander dar. Bewusst nur regional, nicht global - siehe MEMO.md
für die Abwägung (echtes Routing weltweit wäre unverhältnismäßig
aufwändig; die Wirkung des Effekts zeigt sich aber schon an einer
einzelnen Region).
"""

import os

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
AIRPORT_OWN_TRAVEL_HOURS = 31.69  # aus travel_times.csv (5 Umstiege ab London)

EDGES_PATH = "osm_data/birdsville_edges.parquet"
NODES_PATH = "osm_data/birdsville_nodes.parquet"

H3_RESOLUTION = 6  # feiner als die globale Karte (Res. 4), um Straßenverlauf sichtbar zu machen
REGION_HALF_WIDTH_DEG = 3.0

# Grobe Standardgeschwindigkeiten je Straßenklasse (km/h) - die meisten
# OSM-Wege im Outback haben kein maxspeed-Tag.
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
    print("Baue Straßengraphen...")
    G, nodes_df = build_road_graph()
    print(f"{G.number_of_nodes()} Knoten, {G.number_of_edges()} Kanten.")

    origin_node = nearest_node(nodes_df, AIRPORT_LAT, AIRPORT_LON)
    road_hours = nx.single_source_dijkstra_path_length(G, origin_node, weight="hours")
    print(f"{len(road_hours)} Knoten von {AIRPORT_NAME} aus über das Straßennetz erreichbar.")

    reachable_nodes = nodes_df.loc[list(road_hours.keys())]
    reachable_tree = BallTree(np.radians(reachable_nodes[["lat", "lon"]].to_numpy()), metric="haversine")
    reachable_hours = np.array([road_hours[n] for n in reachable_nodes.index])

    grid_df = build_region_grid(AIRPORT_LAT, AIRPORT_LON, REGION_HALF_WIDTH_DEG, H3_RESOLUTION)
    print(f"{len(grid_df)} H3-Kacheln (Res. {H3_RESOLUTION}) in der Region.")

    _, idx = reachable_tree.query(np.radians(grid_df[["lat", "lon"]].to_numpy()), k=1)
    nearest_hours = reachable_hours[idx.ravel()]
    nearest_node_dist_km = np.array([
        haversine_miles(lat, lon, reachable_nodes.iloc[i]["lat"], reachable_nodes.iloc[i]["lon"]) * 1.60934
        for (lat, lon), i in zip(grid_df[["lat", "lon"]].to_numpy(), idx.ravel())
    ])
    # letzte, kurze Strecke von der Kachelmitte zum nächsten erfassten Straßenpunkt
    # noch isotrop dazurechnen, sonst wirkt das Straßennetz "zu perfekt"
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
        (axes[0], "ground_hours_isotropic", "Isotrop (Luftlinie / 80 km/h)"),
        (axes[1], "ground_hours_road", "Straßennetz (OpenStreetMap)"),
    ]:
        ax.set_extent(extent, crs=ccrs.PlateCarree())
        ax.add_feature(cfeature.LAND, facecolor="#f0f0e8", zorder=0)
        ax.add_feature(cfeature.OCEAN, facecolor="#d9e8f5", zorder=0)

        verts = [h3.cell_to_boundary(h) for h in grid_df["h3_index"]]
        verts = [[(lon, lat) for lat, lon in v] for v in verts]
        coll = PolyCollection(
            verts, array=grid_df[col].to_numpy(), cmap=cmap, norm=norm,
            edgecolors="none", transform=ccrs.PlateCarree(), zorder=1,
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
    cbar.set_label("Bodenzeit ab Birdsville Airport (Stunden)")

    fig.suptitle(
        f"{AIRPORT_NAME}: isotrope vs. straßenbasierte Bodenzeit-Modellierung "
        f"(H3 Res. {H3_RESOLUTION}, {REGION_HALF_WIDTH_DEG*2}°-Region)"
    )

    out_path = "birdsville_friction_surface_vs_isotropic.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Karte gespeichert unter {out_path}")


if __name__ == "__main__":
    main()
