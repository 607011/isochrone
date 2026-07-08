"""Friction-Surface-Erreichbarkeitskarte ab einem beliebigen Landpunkt
(Breiten-/Längengrad) statt einem Flughafen.

Vertauscht die Blickrichtung von friction_surface_global.py: dort läuft
ein Dijkstra vom virtuellen Superknoten über alle Flughäfen (deren
Reisezeit ab London schon bekannt ist) zu jeder Landkachel der Welt. Hier
läuft zunächst ein einzelner Dijkstra ab dem gewählten Startpunkt über
denselben gecachten Land-Friction-Graphen zu jedem Flughafen-Pixel - das
liefert dessen individuelle Bodenzeit ab dem Startpunkt statt der bisher
einheitlichen 0h für "echte" Startflughäfen. Diese Bodenzeiten sind die
Kantengewichte des virtuellen Ursprungsknotens in
travel_time.compute_shortest_times (dort seit dieser Änderung auch als
Dict statt nur als Liste möglich), der normale Flugnetz-Dijkstra
kombiniert daraus in einem Rutsch Bodenzeit-zum-Flughafen + Flug-/
Umstiegszeit. Ab dort läuft alles wie in friction_map_from_airport.py
weiter - build_friction_land() nutzt denselben Friction-Graphen erneut,
diesmal in der ursprünglichen Richtung (Flughäfen -> Landkacheln).

Flughäfen ohne Landverbindung zum Startpunkt (z.B. auf Inseln, die der
Friction-Graph nicht mit dem Festland verbindet) bekommen unendliche
Bodenzeit und fallen dadurch automatisch aus den Kandidaten heraus, statt
einen Fehler zu verursachen.
"""

import math

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra
from sklearn.neighbors import BallTree

import config
import friction_surface_global as friction
from data_loading import load_airports, load_routes
from friction_map_from_airport import build_friction_land
from graph_builder import build_graph
from map_from_airport import build_sea
from plot_h3_map import parse_lat_limits, plot_h3_map
from travel_time import compute_shortest_times


def slug_for_point(lat, lon):
    def fmt(v):
        return f"{v:.2f}".replace(".", "p").replace("-", "m")
    return f"point_{fmt(lat)}_{fmt(lon)}"


def build_travel_times_from_point(lat, lon, graph, node_lat, node_lon, airports_df):
    tree = BallTree(np.radians(np.column_stack([node_lat, node_lon])), metric="haversine")
    _, start_idx = tree.query(np.radians([[lat, lon]]), k=1)
    start_idx = int(start_idx[0, 0])

    dist_minutes = dijkstra(graph, directed=True, indices=[start_idx])[0]

    _, airport_node_idx = tree.query(np.radians(airports_df[["lat", "lon"]].to_numpy()), k=1)
    ground_hours = dist_minutes[airport_node_idx.ravel()] / 60

    entry_hours = {
        iata: hours for iata, hours in zip(airports_df["iata"], ground_hours)
        if math.isfinite(hours)
    }
    if not entry_hours:
        raise ValueError("Kein Flughafen ist vom Startpunkt aus über Land erreichbar.")

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
    return pd.DataFrame(rows)


def main(
    lat, lon, label=None, dpi=config.MAP_DPI, show_hubs=config.SHOW_HUBS,
    resolution=config.H3_RESOLUTION, galton=False,
    band_hours=config.GALTON_BAND_HOURS, cmap_name=config.COLORMAP, labels=False, robinson=False,
    grid=False, title=False, lat_limits=None,
):
    origin_label = label or f"{lat:.2f}°, {lon:.2f}°"
    slug = slug_for_point(lat, lon)
    res_suffix = "" if resolution == config.H3_RESOLUTION else f"_res{resolution}"
    galton_suffix = ("_galton10" if cmap_name == "galton10" else "_galton") if galton else ""
    labels_suffix = "_labels" if labels else ""
    proj_suffix = "_robinson" if robinson else ""
    grid_suffix = "_grid" if grid else ""
    title_suffix = "_title" if title else ""
    lat_suffix = f"_lat{lat_limits[0]:g}_{lat_limits[1]:g}" if lat_limits is not None else ""

    airports_df = load_airports(config.AIRPORTS_CSV)
    graph, node_lat, node_lon = friction.load_graph()
    travel_times_df = build_travel_times_from_point(lat, lon, graph, node_lat, node_lon, airports_df)

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
    png = f"h3_travel_times_map_from_{slug}_friction_surface{res_suffix}{galton_suffix}{labels_suffix}{proj_suffix}{grid_suffix}{title_suffix}{lat_suffix}.png"

    travel_times_df.to_csv(travel_times_csv, index=False)
    h3_df.to_csv(h3_csv, index=False)
    ports_df.to_csv(ports_csv, index=False)

    plot_h3_map(
        h3_csv, travel_times_csv, ports_csv, png, [],
        origin_label=origin_label, dpi=dpi, show_hubs=show_hubs, galton=galton,
        band_hours=band_hours, cmap_name=cmap_name, labels=labels, robinson=robinson, grid=grid,
        title=title, lat_limits=lat_limits, origin_points=[(lat, lon)],
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lat", type=float, help="Breitengrad des Startpunkts")
    parser.add_argument("lon", type=float, help="Längengrad des Startpunkts")
    parser.add_argument("--label", default=None, help="Beschriftung für Titel/Legende (Standard: 'lat°, lon°')")
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Auflösung des PNGs")
    parser.add_argument("--no-hubs", action="store_true", help="Flughafen-/Hafen-Punkte ausblenden")
    parser.add_argument("-r", "--resolution", type=int, default=config.H3_RESOLUTION, help="H3-Auflösung (0-15)")
    parser.add_argument(
        "--galton", action="store_true",
        help="Retro-Look: geglättete, diskrete Farbbänder statt stufenloser Skala",
    )
    parser.add_argument(
        "--band-hours", type=float, default=config.GALTON_BAND_HOURS,
        help="Bandbreite in Stunden im --galton-Modus (0-8, 8-16, ...), ignoriert von --cmap galton10",
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
    args = parser.parse_args()

    main(
        args.lat, args.lon, label=args.label, dpi=args.dpi, show_hubs=not args.no_hubs,
        resolution=args.resolution, galton=args.galton, band_hours=args.band_hours, cmap_name=args.cmap,
        labels=args.labels, robinson=args.robinson, grid=args.grid, title=args.title,
        lat_limits=args.lat_limits,
    )
