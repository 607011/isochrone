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

--heli/--jetpack: alternative Einstiegs-Etappe Startpunkt -> Flughafen
per Luftlinie (Haversine) mit fester Geschwindigkeit statt Friction-
Graph, dafür mit begrenzter Reichweite (siehe HELI_SPEED_KMH/
HELI_RANGE_KM/JETPACK_* in config.py). Beide zusammen (oder per
--james-bond) verketten sich: erst so weit wie möglich per Heli, der
Rest der Strecke bis zur Jetpack-Reichweite per Jetpack. Für jeden
Flughafen gewinnt am Ende die schnellere der beiden Einstiegs-Optionen
(Luft oder Boden) - in Reichweite eines Flughafens (civilisation) ist
die Straße oft schneller als das langsame Jetpack, aus großer
Entfernung schlägt die kreuz und quer über Gelände fliegende Luftlinie
den umwegreichen Friction-Graphen.
"""

import math

import numpy as np
import pandas as pd
from scipy.sparse.csgraph import dijkstra
from sklearn.neighbors import BallTree

import config
import friction_surface_global as friction
from data_loading import load_airports, load_routes
from distance import haversine_km_vec
from friction_map_from_airport import build_friction_land
from graph_builder import build_graph
from map_from_airport import build_sea
from plot_h3_map import parse_lat_limits, plot_h3_map
from travel_time import compute_shortest_times


def slug_for_point(lat, lon):
    def fmt(v):
        return f"{v:.2f}".replace(".", "p").replace("-", "m")
    return f"point_{fmt(lat)}_{fmt(lon)}"


def _air_entry_hours(lat, lon, airports_df, heli, jetpack):
    """Luftlinien-Reisezeit je Flughafen per Heli/Jetpack, np.inf außerhalb der Reichweite."""
    hours = np.full(len(airports_df), np.inf)
    if not (heli or jetpack):
        return hours

    dist_km = haversine_km_vec(lat, lon, airports_df["lat"].to_numpy(), airports_df["lon"].to_numpy())

    if heli and jetpack:
        # Erst Heli bis HELI_RANGE_KM, den Rest bis JETPACK_RANGE_KM weiter per Jetpack.
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


def build_travel_times_from_point(lat, lon, graph, node_lat, node_lon, airports_df, heli=False, jetpack=False):
    tree = BallTree(np.radians(np.column_stack([node_lat, node_lon])), metric="haversine")
    _, start_idx = tree.query(np.radians([[lat, lon]]), k=1)
    start_idx = int(start_idx[0, 0])

    dist_minutes = dijkstra(graph, directed=True, indices=[start_idx])[0]

    _, airport_node_idx = tree.query(np.radians(airports_df[["lat", "lon"]].to_numpy()), k=1)
    ground_hours = dist_minutes[airport_node_idx.ravel()] / 60
    air_hours = _air_entry_hours(lat, lon, airports_df, heli, jetpack)
    best_hours = np.minimum(ground_hours, air_hours)

    entry_hours = {
        iata: hours for iata, hours in zip(airports_df["iata"], best_hours)
        if math.isfinite(hours)
    }
    if not entry_hours:
        raise ValueError("Kein Flughafen ist vom Startpunkt aus über Land oder Luft erreichbar.")

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
    grid=False, title=False, lat_limits=None, rivers=False, galton_sigma=config.GALTON_SIGMA_DEG,
    heli=False, jetpack=False,
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
    rivers_suffix = "_rivers" if rivers else ""
    air_suffix = "_bond" if heli and jetpack else ("_heli" if heli else "_jetpack" if jetpack else "")

    airports_df = load_airports(config.AIRPORTS_CSV)
    graph, node_lat, node_lon = friction.load_graph()
    travel_times_df = build_travel_times_from_point(
        lat, lon, graph, node_lat, node_lon, airports_df, heli=heli, jetpack=jetpack,
    )

    land_result = build_friction_land(
        travel_times_df, graph, node_lat, node_lon,
        minutes_path=f"friction_data/land_travel_minutes_from_{slug}{res_suffix}{air_suffix}.npy",
        resolution=resolution,
    )
    sea_result, ports_df = build_sea(land_result, resolution)
    h3_df = pd.concat([land_result, sea_result], ignore_index=True)

    # air_suffix auch in den CSV-Namen, nicht nur im PNG: heli=True ändert
    # travel_times_df/h3_df inhaltlich (andere Einstiegszeiten je Flughafen),
    # ohne den Suffix würde ein --heli-Lauf sonst denselben Dateinamen wie
    # der normale Lauf treffen und ihn stillschweigend überschreiben - siehe
    # MEMO.md zur analogen --cmap galton/galton10-Kollision.
    travel_times_csv = f"travel_times_from_{slug}{air_suffix}.csv"
    h3_csv = f"h3_travel_times_from_{slug}_friction_surface{res_suffix}{air_suffix}.csv"
    ports_csv = f"ports_travel_times_from_{slug}_friction_surface{res_suffix}{air_suffix}.csv"
    png = f"h3_travel_times_map_from_{slug}_friction_surface{res_suffix}{galton_suffix}{labels_suffix}{proj_suffix}{grid_suffix}{title_suffix}{lat_suffix}{rivers_suffix}{air_suffix}.png"

    travel_times_df.to_csv(travel_times_csv, index=False)
    h3_df.to_csv(h3_csv, index=False)
    ports_df.to_csv(ports_csv, index=False)

    plot_h3_map(
        h3_csv, travel_times_csv, ports_csv, png, [],
        origin_label=origin_label, dpi=dpi, show_hubs=show_hubs, galton=galton,
        band_hours=band_hours, cmap_name=cmap_name, labels=labels, robinson=robinson, grid=grid,
        title=title, lat_limits=lat_limits, origin_points=[(lat, lon)], rivers=rivers,
        galton_sigma=galton_sigma,
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
    parser.add_argument(
        "--heli", action="store_true",
        help=f"Einstieg zum Flughafen per Hubschrauber-Luftlinie statt Friction-Graph "
             f"({config.HELI_SPEED_KMH} km/h, Reichweite {config.HELI_RANGE_KM} km) - je Flughafen gewinnt die "
             "schnellere der beiden Optionen",
    )
    parser.add_argument(
        "--jetpack", action="store_true",
        help=f"Wie --heli, aber mit Jetpack ({config.JETPACK_SPEED_KMH} km/h, Reichweite {config.JETPACK_RANGE_KM} km); "
             "zusammen mit --heli verketten sich beide: erst Heli, dann Jetpack für den Rest der Strecke",
    )
    parser.add_argument(
        "--james-bond", action="store_true",
        help="Kurzform für --heli --jetpack zusammen",
    )
    args = parser.parse_args()

    main(
        args.lat, args.lon, label=args.label, dpi=args.dpi, show_hubs=not args.no_hubs,
        resolution=args.resolution, galton=args.galton, band_hours=args.band_hours, cmap_name=args.cmap,
        labels=args.labels, robinson=args.robinson, grid=args.grid, title=args.title,
        lat_limits=args.lat_limits, rivers=args.rivers, galton_sigma=args.galton_sigma,
        heli=args.heli or args.james_bond, jetpack=args.jetpack or args.james_bond,
    )
