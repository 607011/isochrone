"""Friction-surface reachability map from an arbitrary land point
(latitude/longitude) instead of an airport.

Reverses the direction of friction_surface_global.py: there, a Dijkstra
runs from the virtual super-node across all airports (whose travel time
from London is already known) to every land tile in the world. Here, a
Dijkstra first runs from the chosen origin point (more precisely: from
every point reachable from there by heli/jetpack, see below) over the
same cached land-friction graph to every airport pixel - this yields
that airport's individual ground time from the origin point instead of
the previously uniform 0h for "real" origin airports. These ground
times are the edge weights of the virtual origin node in
travel_time.compute_shortest_times (which, since this change, also
accepts a dict instead of just a list), the normal flight-network
Dijkstra then combines ground-time-to-airport + flight/transfer time in
one pass. From there, build_friction_land() runs the same friction
graph again, this time in the original direction (airports -> land
tiles) - identical to the now-removed
friction_map_from_airport.py (see MEMO.md), which only covered the
special case origin point == airport coordinates and turned out to be
redundant once that special case is simply handled here too.

Airports with no land connection to the origin point (e.g. on islands
that the friction graph doesn't connect to the mainland) get infinite
ground time and thereby automatically drop out of the candidates,
instead of causing an error.

--heli/--jetpack: alternative entry leg origin point -> airport via
straight-line distance (Haversine) at a fixed speed instead of the
friction graph, but with limited range (see
HELI_SPEED_KMH/HELI_RANGE_KM/JETPACK_* in config.py). Both together (or
via --james-bond) chain: first as far as possible by heli, the rest of
the distance up to jetpack range by jetpack.

Important: this is no longer a simple "ground or air route, whichever
is faster" (that would waste the distance already flown as soon as you
have to switch to the friction graph partway through - see MEMO.md).
Instead, _combo_ground_minutes() builds a virtual super-node with
edges to EVERY friction-graph node within flight range, edge weight =
that node's individual flight time from the origin point - a single
Dijkstra over the whole graph then yields, for every point in the
world, the minimum over all entry points of (flight time there +
ground time from there to the destination). The origin point itself is
always a free entry point (0h flight time), so it automatically covers
pure walking with no flight at all.
"""

import math

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import dijkstra
from sklearn.neighbors import BallTree

import config
import friction_surface_global as friction
from data_loading import load_airports, load_routes
from distance import haversine_km_vec
from graph_builder import build_graph
from h3_grid import build_grid
from land_mask import is_land
from map_from_airport import build_sea
from plot_h3_map import parse_lat_limits, parse_paper, plot_h3_map
from travel_time import compute_shortest_times


def slug_for_point(lat, lon):
    def fmt(v):
        return f"{v:.2f}".replace(".", "p").replace("-", "m")
    return f"point_{fmt(lat)}_{fmt(lon)}"


def build_friction_land(travel_times_df, graph, node_lat, node_lon, minutes_path, resolution=config.H3_RESOLUTION):
    """Ground time (in hours) per land H3 tile, based on the already
    computed entry times per airport (travel_times_df) - the same
    cached friction graph as everywhere else, just re-solved with the
    super-node weights current for this run (under a second)."""
    minutes = friction.run_dijkstra(graph, node_lat, node_lon, travel_times_df, output_path=minutes_path)
    finite = np.isfinite(minutes)
    tree = BallTree(np.radians(np.column_stack([node_lat[finite], node_lon[finite]])), metric="haversine")

    grid_df = build_grid(resolution)
    on_land = is_land(grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy())
    land_df = grid_df[on_land].reset_index(drop=True)

    _, idx = tree.query(np.radians(land_df[["lat", "lon"]].to_numpy()), k=1)
    land_df["reisezeit_stunden"] = minutes[finite][idx.ravel()] / 60
    land_df["hub_type"] = "airport"
    return land_df


def _air_hours_to(lat, lon, dest_lat, dest_lon, heli, jetpack):
    """Straight-line travel time from the origin point to (dest_lat, dest_lon)
    via heli/jetpack, np.inf outside the range. dest_lat/dest_lon: arbitrary
    numpy arrays - airport coordinates for the entry leg, H3 tile coordinates
    for direct tile coloring (see _apply_air_reach_to_h3)."""
    hours = np.full(len(dest_lat), np.inf)
    if not (heli or jetpack):
        return hours

    dist_km = haversine_km_vec(lat, lon, dest_lat, dest_lon)

    if heli and jetpack:
        # First heli up to HELI_RANGE_KM, then the rest up to JETPACK_RANGE_KM by jetpack.
        within_heli = dist_km <= config.HELI_RANGE_KM
        hours = np.where(within_heli, dist_km / config.HELI_SPEED_KMH, hours)

        remaining_km = dist_km - config.HELI_RANGE_KM
        within_combo = (~within_heli) & (remaining_km <= config.JETPACK_RANGE_KM)
        combo_hours = config.HELI_RANGE_KM / config.HELI_SPEED_KMH + remaining_km / config.JETPACK_SPEED_KMH
        hours = np.where(within_combo, combo_hours, hours)
    elif heli:
        within = dist_km <= config.HELI_RANGE_KM
        hours = np.where(within, dist_km / config.HELI_SPEED_KMH, hours)
    elif jetpack:
        within = dist_km <= config.JETPACK_RANGE_KM
        hours = np.where(within, dist_km / config.JETPACK_SPEED_KMH, hours)

    return hours


def _combo_ground_minutes(lat, lon, graph, node_lat, node_lon, heli, jetpack):
    """Ground time (in minutes) to every node in the friction graph,
    accounting for the fact that you can first fly as far as convenient
    via heli/jetpack and only then continue on foot. A pure "ground time
    from the origin point" (without crediting the distance already
    flown) would waste exactly the distance already covered by air -
    see MEMO.md.

    Technique: a virtual super-node with edges to every friction-graph
    node within flight range, edge weight = that node's individual
    flight time from the origin point (_air_hours_to) - a single
    Dijkstra over the whole graph then yields, per node, the minimum
    over all entry points of (flight time there + ground time from
    there to the node). Exactly the same principle as the virtual
    super-node in friction_surface_global.py (there: airports with
    their own travel time as edge weight), just with flight-range
    points instead of airports.

    The origin point itself is always a free entry point (0h flight
    time), regardless of --heli/--jetpack - automatically covers pure
    walking with no flight at all, without needing a special case
    (without --heli/--jetpack it's simply the only entry point,
    identical to the original single-source Dijkstra).

    Returns (minutes array over all nodes, BallTree over
    node_lat/node_lon) - the tree is reused by callers for their own
    nearest-node queries, instead of building it a second time.
    """
    tree = BallTree(np.radians(np.column_stack([node_lat, node_lon])), metric="haversine")
    _, start_idx = tree.query(np.radians([[lat, lon]]), k=1)
    start_idx = int(start_idx[0, 0])

    entry_air_hours = _air_hours_to(lat, lon, node_lat, node_lon, heli, jetpack)
    entry_air_hours[start_idx] = min(entry_air_hours[start_idx], 0.0)
    entry_idx = np.where(np.isfinite(entry_air_hours))[0]

    n = graph.shape[0]
    graph_coo = graph.tocoo()
    virtual_rows = np.full(len(entry_idx), n)
    virtual_cols = entry_idx
    virtual_weights = entry_air_hours[entry_idx] * 60  # minutes, like the rest of the graph

    all_rows = np.concatenate([graph_coo.row, virtual_rows])
    all_cols = np.concatenate([graph_coo.col, virtual_cols])
    all_data = np.concatenate([graph_coo.data, virtual_weights])
    big = sparse.csr_matrix((all_data, (all_rows, all_cols)), shape=(n + 1, n + 1))
    combo_minutes = dijkstra(big, directed=True, indices=[n])[0][:n]
    return combo_minutes, tree


def build_travel_times_from_point(lat, lon, graph, node_lat, node_lon, airports_df, heli=False, jetpack=False):
    combo_minutes, tree = _combo_ground_minutes(lat, lon, graph, node_lat, node_lon, heli, jetpack)

    _, airport_node_idx = tree.query(np.radians(airports_df[["lat", "lon"]].to_numpy()), k=1)
    best_hours = combo_minutes[airport_node_idx.ravel()] / 60

    entry_hours = {
        iata: hours for iata, hours in zip(airports_df["iata"], best_hours)
        if math.isfinite(hours)
    }
    if not entry_hours:
        raise ValueError("No airport is reachable from the origin point by land or air.")

    routes_df = load_routes(config.ROUTES_CSV, airports_df, include_codeshare=config.INCLUDE_CODESHARE)
    G = build_graph(airports_df, routes_df)
    results = compute_shortest_times(G, entry_hours, config.TRANSFER_HOURS)

    rows = []
    for iata, res in results.items():
        row = airports_df.loc[iata]
        rows.append({
            "iata_code": iata,
            "name": row["name"],
            "lat": row["lat"],
            "lon": row["lon"],
            "reisezeit_stunden": round(res["hours"], 2),
            "anzahl_umstiege": res["stops"],
        })
    return pd.DataFrame(rows), combo_minutes


def _apply_air_reach_to_h3(h3_df, lat, lon, heli, jetpack):
    """Colors H3 tiles (land and sea) within heli/jetpack range directly
    via straight-line distance, instead of only speeding up the entry
    leg to an airport (see _air_hours_to). Competes via min() with the
    already computed value (friction-surface or port model) - whichever
    is faster wins, tile by tile, exactly the same principle as for the
    airport entry. Only has an effect within a few hundred kilometers of
    the origin point (_air_hours_to returns nothing but np.inf outside
    that anyway), but this makes the heli/jetpack range visible on the
    map as an actual radius, instead of only indirectly via faster
    reached airports.
    """
    if not (heli or jetpack):
        return h3_df
    air_hours = _air_hours_to(lat, lon, h3_df["lat"].to_numpy(), h3_df["lon"].to_numpy(), heli, jetpack)
    h3_df["reisezeit_stunden"] = np.minimum(h3_df["reisezeit_stunden"].to_numpy(), air_hours)
    return h3_df


def _apply_combo_ground_to_h3(h3_df, combo_minutes, node_lat, node_lon):
    """Competes combo_minutes (see _combo_ground_minutes - flying as far
    as convenient, then continuing on foot via the friction surface,
    from the origin point) against the previous value per land tile.
    Land tiles only (hub_type == "airport"), since the friction graph is
    pure land and water tiles have no assigned node (for that see
    _apply_air_reach_to_h3 - also covers sea, but only the pure flight
    distance without a walking continuation).
    """
    tree = BallTree(np.radians(np.column_stack([node_lat, node_lon])), metric="haversine")
    is_land = h3_df["hub_type"] == "airport"
    _, idx = tree.query(np.radians(h3_df.loc[is_land, ["lat", "lon"]].to_numpy()), k=1)
    ground_hours = combo_minutes[idx.ravel()] / 60
    h3_df.loc[is_land, "reisezeit_stunden"] = np.minimum(
        h3_df.loc[is_land, "reisezeit_stunden"].to_numpy(), ground_hours,
    )
    return h3_df


def _print_config_overview(
    lat, lon, origin_label, dpi, show_airports, show_ports, resolution, galton, max_hours, cmap_name,
    labels, robinson, grid, title, lat_limits, rivers, galton_sigma, heli, jetpack, paper
):
    """Overview of the configuration in effect for this run, only under
    -v - summarizes what would otherwise be scattered across a dozen
    individual CLI flags, before the actual (sometimes multi-second)
    computation starts."""
    where = f"{origin_label} " if origin_label else ""
    print(f"Start: {where}({lat:.4f}°, {lon:.4f}°)")
    print(f"H3 resolution: {resolution}, Paper: {paper}, DPI: {dpi}")
    print(f"Projection: {'Robinson' if robinson else 'Mercator'}"
          + ("" if robinson or lat_limits is None else f", lat-limits {lat_limits[0]:g}/{lat_limits[1]:g}"))
    if galton:
        print(f"Rendering: Galton color bands (cmap={cmap_name}, max-hours={max_hours:g}, "
              f"galton-sigma={galton_sigma:g}°)")
    else:
        print(f"Rendering: tile mosaic (cmap={cmap_name})")
    overlays = [name for name, on in [
        ("labels", labels), ("grid", grid), ("title", title), ("rivers", rivers),
        ("airports", show_airports), ("ports", show_ports),
    ] if on]
    print(f"Overlays: {', '.join(overlays) if overlays else '(none)'}")
    if heli or jetpack:
        parts = []
        if heli:
            parts.append(f"Heli ({config.HELI_SPEED_KMH} km/h, {config.HELI_RANGE_KM} km range)")
        if jetpack:
            parts.append(f"Jetpack ({config.JETPACK_SPEED_KMH} km/h, {config.JETPACK_RANGE_KM} km range)")
        print(f"First stage of journey: {' + '.join(parts)}")
    else:
        print("First stage of journey: friction-surface only (no --heli or --jetpack)")


def main(
    lat, lon, label=None, dpi=config.MAP_DPI, show_airports=config.SHOW_AIRPORTS, show_ports=config.SHOW_PORTS,
    resolution=config.H3_RESOLUTION, galton=False,
    max_hours=config.GALTON_MAX_HOURS, cmap_name=None, labels=False, robinson=False,
    grid=False, title=False, lat_limits=None, rivers=False, galton_sigma=config.GALTON_SIGMA_DEG,
    heli=False, jetpack=False, verbose=False, paper=None, progress_callback=None,
    city_scalerank=config.CITY_LABEL_MAX_SCALERANK,
):
    # progress_callback: optional hook for the backend (see
    # backend_server.py) - receives the same milestone messages as -v on
    # the console, so a web client can follow the progress of an
    # ongoing render live, without having to read the worker process's
    # stdout. CLI behavior stays unchanged, since progress_callback is
    # never set there.
    def _report(msg):
        if verbose:
            print(msg)
        if progress_callback:
            progress_callback(msg)

    # No coordinate fallback here (unlike earlier) - omitting --label now
    # means no label at all on the map (origin star excluded from the
    # legend, "from <label>" clauses dropped from the colorbar/title/
    # explanation text), not a silent "48.85°, 2.35°" stand-in. See
    # plot_h3_map.py for how it handles origin_label being None.
    origin_label = label
    # --galton implies --rivers/--grid/--labels and --cmap galton (see
    # plot_h3_map.py) - applied here already before the filename is
    # built and the -v overview, so the filename and console output
    # match the image actually rendered, instead of concealing the
    # implied switches.
    rivers = rivers or galton
    grid = grid or galton
    labels = labels or galton
    cmap_name = cmap_name or ("galton" if galton else config.COLORMAP)
    if verbose:
        _print_config_overview(
            lat, lon, origin_label, dpi, show_airports, show_ports, resolution, galton, max_hours, cmap_name,
            labels, robinson, grid, title, lat_limits, rivers, galton_sigma, heli, jetpack, paper
        )
    slug = slug_for_point(lat, lon)
    res_suffix = "" if resolution == config.H3_RESOLUTION else f"_res{resolution}"
    galton_suffix = ("_galton5" if cmap_name == "galton5" else "_galton") if galton else ""
    labels_suffix = "_labels" if labels else ""
    proj_suffix = "_robinson" if robinson else ""
    grid_suffix = "_grid" if grid else ""
    title_suffix = "_title" if title else ""
    lat_suffix = f"_lat{lat_limits[0]:g}_{lat_limits[1]:g}" if lat_limits is not None else ""
    rivers_suffix = "_rivers" if rivers else ""
    air_suffix = "_bond" if heli and jetpack else ("_heli" if heli else "_jetpack" if jetpack else "")
    paper_suffix = f"_{paper}" if paper else ""

    _report("Loading airport data ...")
    airports_df = load_airports(config.AIRPORTS_CSV)
    _report("Loading friction-graph ...")
    graph, node_lat, node_lon = friction.load_graph()
    _report("Calculating combined ground/air travel-times to each airport ...")
    travel_times_df, combo_minutes = build_travel_times_from_point(
        lat, lon, graph, node_lat, node_lon, airports_df, heli=heli, jetpack=jetpack,
    )
    _report(f"{len(travel_times_df)} airports reachable.")

    _report("Distributing ground time across all land tiles ...")
    land_result = build_friction_land(
        travel_times_df, graph, node_lat, node_lon,
        minutes_path=f"friction_data/land_travel_minutes_from_{slug}{res_suffix}{air_suffix}.npy",
        resolution=resolution,
    )
    _report("Building port tiles/ports ...")
    sea_result, ports_df = build_sea(land_result, resolution)
    h3_df = pd.concat([land_result, sea_result], ignore_index=True)
    _report("Applying fly-then-walk ground time to land tiles ...")
    h3_df = _apply_combo_ground_to_h3(h3_df, combo_minutes, node_lat, node_lon)
    if heli or jetpack:
        _report("Coloring tiles within heli/jetpack range...")
        h3_df = _apply_air_reach_to_h3(h3_df, lat, lon, heli, jetpack)

    # air_suffix also in the CSV names, not just the PNG: heli=True
    # changes travel_times_df/h3_df's content (different entry times per
    # airport), without the suffix a --heli run would otherwise hit the
    # same filename as the normal run and silently overwrite it - see
    # MEMO.md on the analogous --cmap galton/galton5 collision.
    travel_times_csv = f"travel_times_from_{slug}{air_suffix}.csv"
    h3_csv = f"h3_travel_times_from_{slug}_friction_surface{res_suffix}{air_suffix}.csv"
    ports_csv = f"ports_travel_times_from_{slug}_friction_surface{res_suffix}{air_suffix}.csv"
    png = f"h3_travel_times_map_from_{slug}_friction_surface{res_suffix}{galton_suffix}{labels_suffix}{proj_suffix}{grid_suffix}{title_suffix}{lat_suffix}{rivers_suffix}{air_suffix}{paper_suffix}.png"

    _report(f"Writing {travel_times_csv}, {h3_csv}, {ports_csv} ...")
    travel_times_df.to_csv(travel_times_csv, index=False)
    h3_df.to_csv(h3_csv, index=False)
    ports_df.to_csv(ports_csv, index=False)

    _report("Drawing map ...")
    plot_h3_map(
        h3_csv, travel_times_csv, ports_csv, png, [],
        origin_label=origin_label, dpi=dpi, show_airports=show_airports, show_ports=show_ports, galton=galton,
        max_hours=max_hours, cmap_name=cmap_name, labels=labels, robinson=robinson, grid=grid,
        title=title, lat_limits=lat_limits, origin_points=[(lat, lon)], rivers=rivers,
        galton_sigma=galton_sigma, heli=heli, jetpack=jetpack, paper=paper,
        city_scalerank=city_scalerank,
    )
    # plot_h3_map() already prints "Map saved as ..." itself
    # (unconditionally, not tied to verbose/_report) - here just the
    # return value for the backend (backend_server.py), which needs to
    # know the filename to read the result back in, without duplicating
    # the suffix logic above.
    return png


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lat", type=float, help="Latitude of the origin point")
    parser.add_argument("lon", type=float, help="Longitude of the origin point")
    parser.add_argument("--label", default=None, help="Label for title/legend (default: 'lat°, lon°')")
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Resolution of the PNG")
    parser.add_argument(
        "--paper", type=parse_paper, default=None, metavar="FORMAT|WIDTHxHEIGHT",
        help="Center the map on a page of this size (landscape), with blank space in "
             "BACKGROUND_COLOR top/bottom instead of an arbitrary, content-dependent "
             "aspect ratio - without --paper it stays as before, tightly cropped around "
             "the actual content (bbox_inches=\"tight\"). Either a name "
             f"({', '.join(sorted(config.PAPER_SIZES_IN))}) or custom centimeter dimensions as "
             "WIDTHxHEIGHT (e.g. 50x60) - poster print shops often don't offer DIN sizes.",
    )
    parser.add_argument("--airports", action="store_true", help="Show airport points (off by default)")
    parser.add_argument("--ports", action="store_true", help="Show port points (off by default)")
    parser.add_argument("-r", "--resolution", type=int, default=config.H3_RESOLUTION, help="H3 resolution (0-15)")
    parser.add_argument(
        "--galton", action="store_true",
        help="Retro look: smoothed, discrete color bands instead of a continuous scale",
    )
    parser.add_argument(
        "--max-hours", type=float, default=config.GALTON_MAX_HOURS,
        help="Total span of the color scale in hours - beyond this the darkest shade "
             "instead of further stretching. Applies to both rendering modes; under "
             "--galton additionally split evenly into ten bands (or five fixed ones "
             "with --cmap galton5).",
    )
    parser.add_argument(
        "--galton-sigma", type=float, default=config.GALTON_SIGMA_DEG,
        help=f"Gaussian smoothing radius in degrees in --galton mode (standard deviation, default {config.GALTON_SIGMA_DEG}°) - "
             "larger = softer/blurrier, smaller = sharper/closer to the raw raster",
    )
    parser.add_argument(
        "--cmap", default=None,
        help="Color palette. Default: viridis_r (standard matplotlib, perceptually uniform) - "
             "except with --galton, then default: galton. Other perceptually uniform "
             "options: plasma_r, inferno_r, magma_r, cividis_r (or without '_r' for the "
             "reversed color direction, or any other matplotlib colormap name). "
             "'galton': the ten real original color values as a fixed, non-interpolated palette "
             "(together with --galton: ten instead of five levels). "
             "'galton5': the same palette reduced to five colors, one per color family "
             "(together with --galton: five instead of ten levels).",
    )
    parser.add_argument(
        "--labels", action="store_true",
        help="Label continents and the most prominent world cities, like Galton's original",
    )
    parser.add_argument(
        "--city-scalerank", type=int, default=config.CITY_LABEL_MAX_SCALERANK, metavar="N",
        help="With --labels: label cities up to this Natural Earth SCALERANK "
             f"(0=most prominent only, higher=more cities; default {config.CITY_LABEL_MAX_SCALERANK}, "
             "~27 cities; 1: ~68; 2: ~99; 3: ~198, at 110m resolution)",
    )
    parser.add_argument(
        "--robinson", action="store_true",
        help="Robinson projection instead of the standard Mercator projection (since Galton's original)",
    )
    parser.add_argument(
        "--grid", action="store_true",
        help="Draw a longitude/latitude grid at 20° intervals",
    )
    parser.add_argument(
        "--title", action="store_true",
        help="Show title (off by default)",
    )
    parser.add_argument(
        "--lat-limits", type=parse_lat_limits, default=None, metavar="NORTH,SOUTH",
        help="Latitude crop of the Mercator map, e.g. '80,-60' (no effect with --robinson); "
             "if not given: 80,-60 (Galton's own crop, independent of --galton)",
    )
    parser.add_argument(
        "--rivers", action="store_true",
        help="Draw major rivers (Natural Earth, 110m), at the same line width as the coastlines",
    )
    parser.add_argument(
        "--heli", action="store_true",
        help=f"Entry to the airport via helicopter straight-line distance instead of the "
             f"friction graph ({config.HELI_SPEED_KMH} km/h, range {config.HELI_RANGE_KM} km) - per airport, "
             "whichever of the two options is faster wins",
    )
    parser.add_argument(
        "--jetpack", action="store_true",
        help=f"Like --heli, but with a jetpack ({config.JETPACK_SPEED_KMH} km/h, range {config.JETPACK_RANGE_KM} km); "
             "together with --heli they chain: first heli, then jetpack for the rest of the distance",
    )
    parser.add_argument(
        "--james-bond", action="store_true",
        help="Shorthand for --heli --jetpack together",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print a configuration overview at start plus progress messages along the way",
    )
    args = parser.parse_args()

    main(
        args.lat, args.lon, label=args.label, dpi=args.dpi, show_airports=args.airports, show_ports=args.ports,
        resolution=args.resolution, galton=args.galton, max_hours=args.max_hours, cmap_name=args.cmap,
        labels=args.labels, robinson=args.robinson, grid=args.grid, title=args.title,
        lat_limits=args.lat_limits, rivers=args.rivers, galton_sigma=args.galton_sigma,
        heli=args.heli or args.james_bond, jetpack=args.jetpack or args.james_bond, verbose=args.verbose,
        paper=args.paper, city_scalerank=args.city_scalerank,
    )
