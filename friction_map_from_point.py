"""Friction-Surface-Erreichbarkeitskarte ab einem beliebigen Landpunkt
(Breiten-/Längengrad) statt einem Flughafen.

Vertauscht die Blickrichtung von friction_surface_global.py: dort läuft
ein Dijkstra vom virtuellen Superknoten über alle Flughäfen (deren
Reisezeit ab London schon bekannt ist) zu jeder Landkachel der Welt. Hier
läuft zunächst ein Dijkstra ab dem gewählten Startpunkt (genauer: von
allen Punkten, die per Heli/Jetpack von dort aus erreichbar sind, siehe
unten) über denselben gecachten Land-Friction-Graphen zu jedem Flughafen-
Pixel - das liefert dessen individuelle Bodenzeit ab dem Startpunkt statt
der bisher einheitlichen 0h für "echte" Startflughäfen. Diese Bodenzeiten
sind die Kantengewichte des virtuellen Ursprungsknotens in
travel_time.compute_shortest_times (dort seit dieser Änderung auch als
Dict statt nur als Liste möglich), der normale Flugnetz-Dijkstra
kombiniert daraus in einem Rutsch Bodenzeit-zum-Flughafen + Flug-/
Umstiegszeit. Ab dort läuft build_friction_land() denselben Friction-
Graphen erneut, diesmal in der ursprünglichen Richtung (Flughäfen ->
Landkacheln) - identisch zum inzwischen entfernten
friction_map_from_airport.py (siehe MEMO.md), das nur den Spezialfall
Startpunkt == Flughafenkoordinaten abdeckte und sich als redundant
herausstellte, sobald man diesen Spezialfall einfach hier miterledigt.

Flughäfen ohne Landverbindung zum Startpunkt (z.B. auf Inseln, die der
Friction-Graph nicht mit dem Festland verbindet) bekommen unendliche
Bodenzeit und fallen dadurch automatisch aus den Kandidaten heraus, statt
einen Fehler zu verursachen.

--heli/--jetpack: alternative Einstiegs-Etappe Startpunkt -> Flughafen
per Luftlinie (Haversine) mit fester Geschwindigkeit statt Friction-
Graph, dafür mit begrenzter Reichweite (siehe HELI_SPEED_KMH/
HELI_RANGE_KM/JETPACK_* in config.py). Beide zusammen (oder per
--james-bond) verketten sich: erst so weit wie möglich per Heli, der
Rest der Strecke bis zur Jetpack-Reichweite per Jetpack.

Wichtig: das ist kein simples "Boden- oder Luftweg, wer schneller ist"
mehr (das würde die bereits geflogene Strecke verschenken, sobald man
zwischendurch auf den Friction-Graphen umsteigen muss - siehe MEMO.md).
Stattdessen wird in _combo_ground_minutes() ein virtueller Superknoten
mit Kanten zu JEDEM Friction-Graph-Knoten in Flugreichweite gebaut,
Kantengewicht = dessen individuelle Flugzeit ab dem Startpunkt - ein
einziger Dijkstra über den ganzen Graphen liefert dann für jeden Punkt
der Welt das Minimum über alle Einstiegspunkte von (Flugzeit dorthin +
Bodenzeit von dort zum Ziel). Der Startpunkt selbst ist dabei immer ein
kostenloser Einstiegspunkt (0h Flugzeit), deckt reines Zufußgehen ganz
ohne Flug also automatisch mit ab.
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
from plot_h3_map import parse_lat_limits, plot_h3_map
from travel_time import compute_shortest_times


def slug_for_point(lat, lon):
    def fmt(v):
        return f"{v:.2f}".replace(".", "p").replace("-", "m")
    return f"point_{fmt(lat)}_{fmt(lon)}"


def build_friction_land(travel_times_df, graph, node_lat, node_lon, minutes_path, resolution=config.H3_RESOLUTION):
    """Bodenzeit (in Stunden) je Land-H3-Kachel, ausgehend von den bereits
    berechneten Einstiegszeiten je Flughafen (travel_times_df) - derselbe
    gecachte Friction-Graph wie überall sonst, nur mit den für diesen Lauf
    aktuellen Superknoten-Gewichten neu gelöst (unter einer Sekunde)."""
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
    """Luftlinien-Reisezeit vom Startpunkt zu (dest_lat, dest_lon) per Heli/Jetpack,
    np.inf außerhalb der Reichweite. dest_lat/dest_lon: beliebige numpy-Arrays -
    Flughafen-Koordinaten für die Einstiegs-Etappe, H3-Kachel-Koordinaten für die
    direkte Kacheleinfärbung (siehe _apply_air_reach_to_h3)."""
    hours = np.full(len(dest_lat), np.inf)
    if not (heli or jetpack):
        return hours

    dist_km = haversine_km_vec(lat, lon, dest_lat, dest_lon)

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


def _combo_ground_minutes(lat, lon, graph, node_lat, node_lon, heli, jetpack):
    """Bodenzeit (in Minuten) zu jedem Knoten im Friction-Graphen, unter
    Berücksichtigung, dass man zunächst per Heli/Jetpack so weit wie günstig
    fliegen und erst danach zu Fuß weiterlaufen kann. Eine reine "Bodenzeit
    ab dem Startpunkt" (ohne die geflogene Strecke gutzuschreiben) würde
    genau die bereits zurückgelegte Flugstrecke verschenken - siehe MEMO.md.

    Technik: virtueller Superknoten mit Kanten zu jedem Friction-Graph-Knoten
    in Flugreichweite, Kantengewicht = dessen individuelle Flugzeit ab dem
    Startpunkt (_air_hours_to) - ein einziger Dijkstra über den ganzen Graphen
    liefert dann je Knoten das Minimum über alle Einstiegspunkte von
    (Flugzeit dorthin + Bodenzeit von dort zum Knoten). Exakt dasselbe
    Prinzip wie der virtuelle Superknoten in friction_surface_global.py
    (dort: Flughäfen mit ihrer eigenen Reisezeit als Kantengewicht), nur mit
    Flugreichweiten-Punkten statt Flughäfen.

    Der Startpunkt selbst ist immer ein kostenloser Einstiegspunkt (0h
    Flugzeit), unabhängig von --heli/--jetpack - deckt reines Zufußgehen
    ganz ohne Flug automatisch mit ab, ohne dass ein Sonderfall nötig wäre
    (ohne --heli/--jetpack ist er dadurch schlicht der einzige
    Einstiegspunkt, identisch zum ursprünglichen Einzelquellen-Dijkstra).

    Gibt (Minuten-Array über alle Knoten, BallTree über node_lat/node_lon)
    zurück - der Tree wird von den Aufrufern für eigene Nearest-Node-
    Abfragen wiederverwendet, statt ihn ein zweites Mal aufzubauen.
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
    virtual_weights = entry_air_hours[entry_idx] * 60  # Minuten, wie der Rest des Graphen

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
    return pd.DataFrame(rows), combo_minutes


def _apply_air_reach_to_h3(h3_df, lat, lon, heli, jetpack):
    """Färbt H3-Kacheln (Land und See) innerhalb der Heli-/Jetpack-Reichweite direkt
    per Luftlinie ein, statt nur die Einstiegs-Etappe zu einem Flughafen zu
    beschleunigen (siehe _air_hours_to). Konkurriert per min() mit dem bereits
    berechneten Wert (Friction-Surface- bzw. Hafen-Modell) - wer schneller ist,
    gewinnt, kachelweise, exakt dasselbe Prinzip wie beim Flughafen-Einstieg.
    Wirkt sich nur innerhalb weniger hundert Kilometer um den Startpunkt aus
    (außerhalb liefert _air_hours_to ohnehin nur np.inf), macht die Heli-/
    Jetpack-Reichweite dadurch aber als echten Umkreis auf der Karte sichtbar,
    statt nur indirekt über schneller erreichte Flughäfen.
    """
    if not (heli or jetpack):
        return h3_df
    air_hours = _air_hours_to(lat, lon, h3_df["lat"].to_numpy(), h3_df["lon"].to_numpy(), heli, jetpack)
    h3_df["reisezeit_stunden"] = np.minimum(h3_df["reisezeit_stunden"].to_numpy(), air_hours)
    return h3_df


def _apply_combo_ground_to_h3(h3_df, combo_minutes, node_lat, node_lon):
    """Konkurriert combo_minutes (siehe _combo_ground_minutes - Fliegen so
    weit wie günstig, dann per Friction-Surface zu Fuß weiter, ab dem
    Startpunkt) gegen den bisherigen Wert je Landkachel. Nur für Landkacheln
    (hub_type == "airport"), da der Friction-Graph reines Land ist und
    Wasserkacheln keinen zugeordneten Knoten haben (dafür siehe
    _apply_air_reach_to_h3 - deckt auch See ab, aber nur die reine
    Flugstrecke ohne Fußweg-Fortsetzung).
    """
    tree = BallTree(np.radians(np.column_stack([node_lat, node_lon])), metric="haversine")
    is_land = h3_df["hub_type"] == "airport"
    _, idx = tree.query(np.radians(h3_df.loc[is_land, ["lat", "lon"]].to_numpy()), k=1)
    ground_hours = combo_minutes[idx.ravel()] / 60
    h3_df.loc[is_land, "reisezeit_stunden"] = np.minimum(
        h3_df.loc[is_land, "reisezeit_stunden"].to_numpy(), ground_hours,
    )
    return h3_df


def main(
    lat, lon, label=None, dpi=config.MAP_DPI, show_airports=config.SHOW_AIRPORTS, show_ports=config.SHOW_PORTS,
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
    travel_times_df, combo_minutes = build_travel_times_from_point(
        lat, lon, graph, node_lat, node_lon, airports_df, heli=heli, jetpack=jetpack,
    )

    land_result = build_friction_land(
        travel_times_df, graph, node_lat, node_lon,
        minutes_path=f"friction_data/land_travel_minutes_from_{slug}{res_suffix}{air_suffix}.npy",
        resolution=resolution,
    )
    sea_result, ports_df = build_sea(land_result, resolution)
    h3_df = pd.concat([land_result, sea_result], ignore_index=True)
    h3_df = _apply_combo_ground_to_h3(h3_df, combo_minutes, node_lat, node_lon)
    h3_df = _apply_air_reach_to_h3(h3_df, lat, lon, heli, jetpack)

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
        origin_label=origin_label, dpi=dpi, show_airports=show_airports, show_ports=show_ports, galton=galton,
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
    parser.add_argument("--airports", action="store_true", help="Flughafen-Punkte einblenden (standardmäßig aus)")
    parser.add_argument("--ports", action="store_true", help="Hafen-Punkte einblenden (standardmäßig aus)")
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
        args.lat, args.lon, label=args.label, dpi=args.dpi, show_airports=args.airports, show_ports=args.ports,
        resolution=args.resolution, galton=args.galton, band_hours=args.band_hours, cmap_name=args.cmap,
        labels=args.labels, robinson=args.robinson, grid=args.grid, title=args.title,
        lat_limits=args.lat_limits, rivers=args.rivers, galton_sigma=args.galton_sigma,
        heli=args.heli or args.james_bond, jetpack=args.jetpack or args.james_bond,
    )
