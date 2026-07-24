"""Reachability map from an arbitrary airport instead of London.

Uses exactly the same pipeline as main.py/main_h3.py/plot_h3_map.py,
just with a different origin airport - e.g. to see what the world looks
like from an airport that itself is only reachable from London via
several transfers.
"""

import pandas as pd

import config
from data_loading import load_airports, load_routes
from graph_builder import build_graph
from h3_grid import build_grid
from land_mask import is_land
from nearest_hub import assign_travel_times, nearest_value
from plot_h3_map import parse_lat_limits, parse_paper, plot_h3_map
from ports_loading import load_ports
from travel_time import compute_shortest_times


def build_travel_times(origin_iatas):
    airports_df = load_airports(config.AIRPORTS_CSV)
    routes_df = load_routes(config.ROUTES_CSV, airports_df, include_codeshare=config.INCLUDE_CODESHARE)
    G = build_graph(airports_df, routes_df)
    results = compute_shortest_times(G, origin_iatas, config.TRANSFER_HOURS)

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
    return pd.DataFrame(rows)


def build_sea(land_result, resolution=config.H3_RESOLUTION):
    """Ports + water tiles for an already computed land-tile travel time.

    Regardless of how land_result came about (isotropic circle model
    here, or the friction-surface model in
    friction_map_from_airport.py) - a port simply gets the travel time
    of its nearest land tile, water tiles then get the travel time of
    the fastest port within range. See main_h3.py/MEMO.md for the
    rationale. resolution must match the one used for land_result,
    otherwise land and water tiles won't fit together seamlessly.
    """
    grid_df = build_grid(resolution)
    on_land = is_land(grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy())
    sea_df = grid_df[~on_land].reset_index(drop=True)

    ports_df = load_ports(config.PORTS_CORRECTED_CSV)
    ports_df["reisezeit_stunden"] = nearest_value(ports_df, land_result, "reisezeit_stunden")

    sea_result = assign_travel_times(
        sea_df, ports_df, config.MAX_PORT_DISTANCE_KM, config.SEA_SPEED_KMH,
        hub_id_col="unlocode",
    )
    sea_result["hub_type"] = "port"
    return sea_result, ports_df


def build_h3(travel_times_df, resolution=config.H3_RESOLUTION):
    grid_df = build_grid(resolution)
    on_land = is_land(grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy())
    land_df = grid_df[on_land].reset_index(drop=True)

    land_result = assign_travel_times(
        land_df, travel_times_df, config.MAX_AIRPORT_DISTANCE_KM, config.GROUND_SPEED_KMH,
        hub_id_col="iata_code",
    )
    land_result["hub_type"] = "airport"

    sea_result, ports_df = build_sea(land_result, resolution)
    return pd.concat([land_result, sea_result], ignore_index=True), ports_df


def slug_for(iata, name):
    return iata.lower() + "_" + "".join(c if c.isalnum() else "_" for c in name.lower())


def main(
    origin_iata, dpi=config.MAP_DPI, show_airports=config.SHOW_AIRPORTS, show_ports=config.SHOW_PORTS,
    resolution=config.H3_RESOLUTION, galton=False,
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

    travel_times_df = build_travel_times([origin_iata])
    if origin_iata not in travel_times_df["iata_code"].values:
        raise ValueError(f"{origin_iata} is not reachable/present in the flight network.")

    origin_row = travel_times_df[travel_times_df["iata_code"] == origin_iata].iloc[0]
    slug = slug_for(origin_iata, origin_row["name"])
    res_suffix = "" if resolution == config.H3_RESOLUTION else f"_res{resolution}"
    galton_suffix = ("_galton5" if cmap_name == "galton5" else "_galton") if galton else ""
    labels_suffix = "_labels" if labels else ""
    proj_suffix = "_robinson" if robinson else ""
    grid_suffix = "_grid" if grid else ""
    title_suffix = "_title" if title else ""
    lat_suffix = f"_lat{lat_limits[0]:g}_{lat_limits[1]:g}" if lat_limits is not None else ""
    rivers_suffix = "_rivers" if rivers else ""
    paper_suffix = f"_{paper}" if paper else ""

    h3_df, ports_df = build_h3(travel_times_df, resolution)

    travel_times_csv = f"travel_times_from_{slug}.csv"
    h3_csv = f"h3_travel_times_from_{slug}{res_suffix}.csv"
    ports_csv = f"ports_travel_times_from_{slug}{res_suffix}.csv"
    png = f"h3_travel_times_map_from_{slug}{res_suffix}{galton_suffix}{labels_suffix}{proj_suffix}{grid_suffix}{title_suffix}{lat_suffix}{rivers_suffix}{paper_suffix}.png"

    travel_times_df.to_csv(travel_times_csv, index=False)
    h3_df.to_csv(h3_csv, index=False)
    ports_df.to_csv(ports_csv, index=False)

    plot_h3_map(
        h3_csv, travel_times_csv, ports_csv, png, [origin_iata],
        origin_label=origin_row["name"], dpi=dpi, show_airports=show_airports, show_ports=show_ports, galton=galton,
        max_hours=max_hours, cmap_name=cmap_name, labels=labels, robinson=robinson, grid=grid,
        title=title, lat_limits=lat_limits, rivers=rivers, galton_sigma=galton_sigma, paper=paper,
        city_scalerank=city_scalerank,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iata", nargs="?", default="THU", help="IATA code of the origin airport")
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
    parser.add_argument("-r", "--resolution", type=int, default=config.H3_RESOLUTION, help="H3 resolution (0-15)")
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
        args.iata, dpi=args.dpi, show_airports=args.airports, show_ports=args.ports, resolution=args.resolution, galton=args.galton,
        max_hours=args.max_hours, cmap_name=args.cmap, labels=args.labels, robinson=args.robinson,
        grid=args.grid, title=args.title, lat_limits=args.lat_limits, rivers=args.rivers,
        galton_sigma=args.galton_sigma, paper=args.paper, city_scalerank=args.city_scalerank,
    )
