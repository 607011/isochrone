"""Global anisotropic ground time via the MAP friction-surface raster.

Replaces the isotropic GROUND_SPEED_KMH circle model for land tiles
with a real cost-distance computation over a global terrain-friction
raster (Malaria Atlas Project / Weiss et al., "2020 motorized friction
surface", 1 km resolution, minutes per meter). See
friction_surface_demo.py for the small-scale variant with a real OSM
road network (Birdsville) - this script is the global counterpart, but
with a precomputed friction raster instead of live routing, because
live routing worldwide would be disproportionately expensive (see
MEMO.md).

The raster also has valid (slow) values over open ocean, presumably
meant for boat/ferry connections - that would collide with the
existing sea model (main_h3.py, via ports). So it's masked to pure
land (global-land-mask, as in the rest of the project), water pixels
are removed from the graph instead of allowed as slow edges.

Computes in three phases, each cacheable on its own:
1. Load the raster, downsample to ~11 km resolution (min-pooling, so
   thin fast roads don't disappear during coarsening).
2. Build a graph from that over land pixels only (8-neighborhood, edge
   weight = friction * real distance in meters).
3. From a virtual super-node connected to every airport pixel via an
   edge with weight = that airport's own travel time from London, run
   Dijkstra globally once (scipy) - directly yields flight time + real
   (anisotropic) ground time combined, exactly the same principle as
   the virtual origin node in travel_time.py/nearest_hub.py, just over
   a raster grid instead of a radius search.
"""

import time

import numpy as np
import rasterio
from global_land_mask import globe
from scipy import sparse
from scipy.sparse.csgraph import dijkstra
from sklearn.neighbors import BallTree

import config

FRICTION_TIF = "friction_data/2020_motorized_friction_surface.geotiff"
DOWNSAMPLE_FACTOR = 12  # ~1km -> ~11km pixel edge length
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
    print(f"Raster downsampled to {down.shape} in {time.time()-t0:.0f}s")
    return down


def build_land_graph(friction):
    h, w = friction.shape
    lat = 85 - PIXEL_DEG * (np.arange(h) + 0.5)
    lon = -180 + PIXEL_DEG * (np.arange(w) + 0.5)
    lon_grid, lat_grid = np.meshgrid(lon, lat)

    is_land = globe.is_land(lat_grid, lon_grid) & ~np.isnan(friction)
    print(f"{is_land.sum()} land pixels out of {is_land.size}.")

    node_id = np.full((h, w), -1, dtype=np.int64)
    node_id[is_land] = np.arange(is_land.sum())
    node_lat = lat_grid[is_land]
    node_lon = lon_grid[is_land]

    lat_step_km = config.EARTH_RADIUS_KM * np.radians(PIXEL_DEG)

    # Build edges only via explicit slicing (no np.roll!) - roll wraps
    # around at the edge to the opposite side of the map, which on a
    # sign mix-up silently produces wrong edges instead of cleanly
    # crashing. The cost of this is missing edges across the
    # antimeridian (~180° longitude) - a small, accepted gap, see
    # MEMO.md.
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
    print(f"Graph built: {n} nodes, {graph.nnz} edges.")
    return graph, node_lat, node_lon


def load_graph():
    """Loads the cached, origin-independent land graph.

    The graph itself (nodes, edges, friction) doesn't depend on the
    origin airport - only the virtual super-node's weights in
    run_dijkstra() do. So for a new origin only run_dijkstra() needs to
    run again, not downsample_friction()/build_land_graph() (minutes
    instead of minutes+seconds).
    """
    graph = sparse.load_npz(CACHE_GRAPH)
    node_latlon = np.load(CACHE_NODE_LATLON)
    return graph, node_latlon[:, 0], node_latlon[:, 1]


def run_dijkstra(graph, node_lat, node_lon, airports_df, output_path=CACHE_TRAVEL_MINUTES):
    # Measures the whole function, not just the actual dijkstra() call:
    # that previously sat right before the timing, so the BallTree
    # construction and assembling the super-node matrix (together
    # often about as much time as Dijkstra itself) went by unnoticed -
    # the "in 0s" output was correct for the measured part, but
    # suggested a much shorter total runtime than actually elapsed.
    t0 = time.time()
    n = graph.shape[0]
    tree = BallTree(np.radians(np.column_stack([node_lat, node_lon])), metric="haversine")
    _, airport_node_idx = tree.query(np.radians(airports_df[["lat", "lon"]].to_numpy()), k=1)
    airport_node_idx = airport_node_idx.ravel()

    # virtual super-node (index n) -> airport pixel, edge weight =
    # the airport's own travel time from its origin, in minutes.
    graph_coo = graph.tocoo()
    virtual_rows = np.full(len(airports_df), n)
    virtual_cols = airport_node_idx
    virtual_weights = airports_df["reisezeit_stunden"].to_numpy() * 60

    all_rows = np.concatenate([graph_coo.row, virtual_rows])
    all_cols = np.concatenate([graph_coo.col, virtual_cols])
    all_data = np.concatenate([graph_coo.data, virtual_weights])
    big = sparse.csr_matrix((all_data, (all_rows, all_cols)), shape=(n + 1, n + 1))

    dist = dijkstra(big, directed=True, indices=[n])[0]
    # .1f instead of .0f: Dijkstra itself usually runs in under a second
    # on the cached graph - with .0f this would always have shown "0s",
    # regardless of the actual rounding error above.
    print(f"Dijkstra finished in {time.time()-t0:.1f}s.")
    minutes = dist[:n]
    np.save(output_path, minutes.astype(np.float32))
    return minutes


def main():
    # Builds only the origin-independent cache (downsampled raster +
    # land graph) that load_graph() reloads - this is the one-time setup
    # step the web backend needs (see friction_map_from_point.py, which
    # calls load_graph() + run_dijkstra() itself with its own per-point
    # origin). The London-specific result (run_dijkstra() seeded from
    # doc/travel_times.csv) isn't computed here anymore - it's only
    # consumed by doc/friction_surface_map.py's own example pipeline, so
    # it's computed there instead, rather than requiring doc/main.py's
    # output just to set up the backend.
    friction = downsample_friction()
    build_land_graph(friction)


if __name__ == "__main__":
    main()
