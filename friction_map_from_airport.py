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

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

import config
import friction_surface_global as friction
from h3_grid import build_grid
from land_mask import is_land
from map_from_airport import build_sea, build_travel_times, slug_for
from plot_h3_map import parse_lat_limits, plot_h3_map


def build_friction_land(travel_times_df, graph, node_lat, node_lon, minutes_path, resolution=config.H3_RESOLUTION):
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


def main(
    origin_iata, dpi=config.MAP_DPI, show_hubs=config.SHOW_HUBS,
    resolution=config.H3_RESOLUTION, galton=False,
    band_hours=config.GALTON_BAND_HOURS, cmap_name=config.COLORMAP, labels=False, robinson=False,
    grid=False, title=False, lat_limits=None, rivers=False, galton_sigma=config.GALTON_SIGMA_DEG,
):
    travel_times_df = build_travel_times([origin_iata])
    if origin_iata not in travel_times_df["iata_code"].values:
        raise ValueError(f"{origin_iata} ist im Flugnetz nicht erreichbar/vorhanden.")

    origin_row = travel_times_df[travel_times_df["iata_code"] == origin_iata].iloc[0]
    slug = slug_for(origin_iata, origin_row["name"])
    res_suffix = "" if resolution == config.H3_RESOLUTION else f"_res{resolution}"
    galton_suffix = ("_galton10" if cmap_name == "galton10" else "_galton") if galton else ""
    labels_suffix = "_labels" if labels else ""
    proj_suffix = "_robinson" if robinson else ""
    grid_suffix = "_grid" if grid else ""
    title_suffix = "_title" if title else ""
    lat_suffix = f"_lat{lat_limits[0]:g}_{lat_limits[1]:g}" if lat_limits is not None else ""
    rivers_suffix = "_rivers" if rivers else ""

    graph, node_lat, node_lon = friction.load_graph()
    land_result = build_friction_land(
        travel_times_df, graph, node_lat, node_lon,
        minutes_path=f"friction_data/land_travel_minutes_from_{slug}{res_suffix}.npy",
        resolution=resolution,
    )
    sea_result, ports_df = build_sea(land_result, resolution)
    h3_df = pd.concat([land_result, sea_result], ignore_index=True)

    travel_times_csv = f"travel_times_from_{slug}.csv"
    h3_csv = f"h3_travel_times_from_{slug}_friction_surface{res_suffix}.csv"
    ports_csv = f"ports_travel_times_from_{slug}_friction_surface{res_suffix}.csv"
    png = f"h3_travel_times_map_from_{slug}_friction_surface{res_suffix}{galton_suffix}{labels_suffix}{proj_suffix}{grid_suffix}{title_suffix}{lat_suffix}{rivers_suffix}.png"

    travel_times_df.to_csv(travel_times_csv, index=False)
    h3_df.to_csv(h3_csv, index=False)
    ports_df.to_csv(ports_csv, index=False)

    plot_h3_map(
        h3_csv, travel_times_csv, ports_csv, png, [origin_iata],
        origin_label=origin_row["name"], dpi=dpi, show_hubs=show_hubs, galton=galton,
        band_hours=band_hours, cmap_name=cmap_name, labels=labels, robinson=robinson, grid=grid,
        title=title, lat_limits=lat_limits, rivers=rivers, galton_sigma=galton_sigma,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iata", nargs="?", default="THU", help="IATA-Code des Start-Flughafens")
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Auflösung des PNGs")
    parser.add_argument("--no-hubs", action="store_true", help="Flughafen-/Hafen-Punkte ausblenden")
    parser.add_argument("-r", "--resolution", type=int, default=config.H3_RESOLUTION, help="H3-Auflösung (0-15)")
    parser.add_argument(
        "--galton", action="store_true",
        help="Retro-Look: geglättete, diskrete Farbbänder statt stufenloser Skala",
    )
    parser.add_argument(
        "--band-hours", type=float, default=config.GALTON_BAND_HOURS,
        help="Bandbreite in Stunden im --galton-Modus (0-4, 4-8, ...), ignoriert von --cmap galton10",
    )
    parser.add_argument(
        "--galton-sigma", type=float, default=config.GALTON_SIGMA_DEG,
        help=f"Gauß-Glättungsradius in Grad im --galton-Modus (Standardabweichung, Standard {config.GALTON_SIGMA_DEG}°) - "
             "größer = weicher/verwaschener, kleiner = schärfer/näher am Rohraster",
    )
    parser.add_argument(
        "--cmap", default=config.COLORMAP,
        help="Farbpalette. Standard: viridis_r (Standard-Matplotlib, perzeptuell gleichmaessig). "
             "Weitere perzeptuell gleichmaessige Optionen: plasma_r, inferno_r, magma_r, cividis_r "
             "(oder ohne '_r' fuer umgekehrte Farbrichtung, oder jeder andere matplotlib-Colormap-Name). "
             "'galton': interpolierte, an das Original angelehnte Palette. "
             "'galton10': dieselben zehn Originalfarben als feste, nicht interpolierte Palette "
             "(zusammen mit --galton: exakt zehn Stufen statt --band-hours).",
    )
    parser.add_argument(
        "--labels", action="store_true",
        help="Kontinente und wichtigste Weltstädte beschriften, wie bei Galtons Original",
    )
    parser.add_argument(
        "--robinson", action="store_true",
        help="Robinson-Projektion statt der (seit Galtons Original) Standard-Mercator-Projektion",
    )
    parser.add_argument(
        "--grid", action="store_true",
        help="Längen-/Breitengrad-Raster in 20°-Abständen einzeichnen",
    )
    parser.add_argument(
        "--title", action="store_true",
        help="Überschrift einblenden (standardmäßig aus)",
    )
    parser.add_argument(
        "--lat-limits", type=parse_lat_limits, default=None, metavar="NORD,SÜD",
        help="Breitengrad-Zuschnitt der Mercator-Karte, z.B. '80,-60' (wirkungslos bei --robinson); "
             "ohne Angabe: 80,-60 unter --galton, sonst 85,-85",
    )
    parser.add_argument(
        "--rivers", action="store_true",
        help="Große Flüsse einzeichnen (Natural Earth, 110m), in derselben Strichstärke wie die Küstenlinien",
    )
    args = parser.parse_args()

    main(
        args.iata, dpi=args.dpi, show_hubs=not args.no_hubs, resolution=args.resolution, galton=args.galton,
        band_hours=args.band_hours, cmap_name=args.cmap, labels=args.labels, robinson=args.robinson,
        grid=args.grid, title=args.title, lat_limits=args.lat_limits, rivers=args.rivers,
        galton_sigma=args.galton_sigma,
    )
