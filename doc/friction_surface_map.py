"""Builds an H3 map from the global friction-surface result
(friction_surface_global.py) and places it alongside the previous
isotropic map.

Runs the London-specific Dijkstra itself (friction_surface_global.load_graph()
+ run_dijkstra(), seeded from doc/travel_times.csv) - that step used to live
in friction_surface_global.py's own main(), but it's only ever consumed here,
not by the web backend, so it moved to where it's actually used.

Only land tiles get the new, road-based value - water tiles come
unchanged from main_h3.py (its port model is independent of the
friction-surface raster, see friction_surface_global.py). At a
resolution other than the default, main_h3.py -r <resolution> must
have been run first, so the water tiles match the chosen resolution.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

# Moved to doc/ (standalone example script, not part of the web
# backend's dependency chain) - the modules below still live in the
# project root, so it needs to be on sys.path regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import friction_surface_global as friction
from h3_grid import build_grid
from land_mask import is_land
from main_h3 import _output_path_for
from plot_h3_map import parse_lat_limits, parse_paper, plot_h3_map

OUTPUT_CSV = "doc/h3_travel_times_london_friction_surface.csv"
OUTPUT_PNG = "doc/h3_travel_times_map_london_friction_surface_land.png"


def main(
    resolution=config.H3_RESOLUTION, dpi=config.MAP_DPI, show_airports=config.SHOW_AIRPORTS,
    show_ports=config.SHOW_PORTS, galton=False,
    max_hours=config.GALTON_MAX_HOURS, cmap_name=None, labels=False, robinson=False,
    grid=False, title=False, lat_limits=None, rivers=False, galton_sigma=config.GALTON_SIGMA_DEG,
    paper=None, city_scalerank=config.CITY_LABEL_MAX_SCALERANK,
):
    # --galton implies --rivers/--grid/--labels and --cmap galton (see
    # plot_h3_map.py) - applied here already before the filename is
    # built, so the filename matches the image actually rendered.
    rivers = rivers or galton
    grid = grid or galton
    labels = labels or galton
    cmap_name = cmap_name or ("galton" if galton else config.COLORMAP)

    # The London-specific Dijkstra run lives here now, not in
    # friction_surface_global.py's own main() - it's only this example
    # script that needs it (see friction_surface_global.py for why),
    # and run_dijkstra() itself is fast (~1-2s), so recomputing it here
    # rather than caching a separate copy matches how
    # friction_map_from_point.py already treats it for its own origins.
    airports_df = pd.read_csv(config.OUTPUT_CSV)
    graph, node_lat, node_lon = friction.load_graph()
    minutes = friction.run_dijkstra(graph, node_lat, node_lon, airports_df)
    finite = np.isfinite(minutes)
    tree = BallTree(np.radians(np.column_stack([node_lat, node_lon]))[finite], metric="haversine")

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
    galton_suffix = ("_galton5" if cmap_name == "galton5" else "_galton") if galton else ""
    labels_suffix = "_labels" if labels else ""
    proj_suffix = "_robinson" if robinson else ""
    grid_suffix = "_grid" if grid else ""
    title_suffix = "_title" if title else ""
    lat_suffix = f"_lat{lat_limits[0]:g}_{lat_limits[1]:g}" if lat_limits is not None else ""
    rivers_suffix = "_rivers" if rivers else ""
    paper_suffix = f"_{paper}" if paper else ""
    output_csv = OUTPUT_CSV.replace(".csv", f"{res_suffix}.csv")
    output_png = OUTPUT_PNG.replace(
        ".png",
        f"{res_suffix}{galton_suffix}{labels_suffix}{proj_suffix}{grid_suffix}{title_suffix}{lat_suffix}{rivers_suffix}{paper_suffix}.png",
    )
    combined.to_csv(output_csv, index=False)

    covered = combined["reisezeit_stunden"].notna().sum()
    print(f"{covered} of {len(combined)} tiles covered "
          f"(land via friction surface: {land_df['reisezeit_stunden'].notna().sum()}/{len(land_df)}).")

    ports_csv_in = _output_path_for(config.OUTPUT_PORTS_CSV, resolution)
    plot_h3_map(
        output_csv, config.OUTPUT_CSV, ports_csv_in, output_png, config.ORIGIN_AIRPORTS,
        dpi=dpi, show_airports=show_airports, show_ports=show_ports, galton=galton, max_hours=max_hours, cmap_name=cmap_name,
        labels=labels, robinson=robinson, grid=grid, title=title, lat_limits=lat_limits, rivers=rivers,
        galton_sigma=galton_sigma, paper=paper, city_scalerank=city_scalerank,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-r", "--resolution", type=int, default=config.H3_RESOLUTION, help="H3 resolution (0-15)")
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
    args = parser.parse_args()

    main(
        resolution=args.resolution, dpi=args.dpi, show_airports=args.airports, show_ports=args.ports, galton=args.galton,
        max_hours=args.max_hours, cmap_name=args.cmap, labels=args.labels, robinson=args.robinson,
        grid=args.grid, title=args.title, lat_limits=args.lat_limits, rivers=args.rivers,
        galton_sigma=args.galton_sigma, paper=args.paper, city_scalerank=args.city_scalerank,
    )
