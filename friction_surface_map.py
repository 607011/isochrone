"""Baut aus dem globalen Friction-Surface-Ergebnis (friction_surface_global.py)
eine H3-Karte und stellt sie neben die bisherige isotrope Karte.

Nur Landkacheln bekommen den neuen, straßenbasierten Wert - Wasserkacheln
kommen unverändert aus main_h3.py (dessen Häfen-Modell ist unabhängig
vom Friction-Surface-Raster, siehe friction_surface_global.py). Bei einer
anderen als der Standard-Auflösung muss main_h3.py -r <auflösung> vorher
gelaufen sein, damit die Wasserkacheln zur gewählten Auflösung passen.
"""

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

import config
from h3_grid import build_grid
from land_mask import is_land
from main_h3 import _output_path_for
from plot_h3_map import parse_lat_limits, parse_paper, plot_h3_map

TRAVEL_MINUTES_NPY = "friction_data/land_travel_minutes.npy"
NODE_LATLON_NPY = "friction_data/land_node_latlon.npy"

OUTPUT_CSV = "h3_travel_times_london_friction_surface.csv"
OUTPUT_PNG = "h3_travel_times_map_london_friction_surface_land.png"


def main(
    resolution=config.H3_RESOLUTION, dpi=config.MAP_DPI, show_airports=config.SHOW_AIRPORTS,
    show_ports=config.SHOW_PORTS, galton=False,
    max_hours=config.GALTON_MAX_HOURS, cmap_name=None, labels=False, robinson=False,
    grid=False, title=False, lat_limits=None, rivers=False, galton_sigma=config.GALTON_SIGMA_DEG,
    paper=None,
):
    # --galton impliziert --rivers/--grid/--labels und --cmap galton (siehe
    # plot_h3_map.py) - hier schon vor der Dateinamens-Bildung angewendet,
    # damit der Dateiname zum tatsächlich gezeichneten Bild passt.
    rivers = rivers or galton
    grid = grid or galton
    labels = labels or galton
    cmap_name = cmap_name or ("galton" if galton else config.COLORMAP)

    minutes = np.load(TRAVEL_MINUTES_NPY)
    node_latlon = np.load(NODE_LATLON_NPY)
    finite = np.isfinite(minutes)
    tree = BallTree(np.radians(node_latlon[finite]), metric="haversine")

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
    print(f"{covered} von {len(combined)} Kacheln abgedeckt "
          f"(Land via Friction Surface: {land_df['reisezeit_stunden'].notna().sum()}/{len(land_df)}).")

    ports_csv_in = _output_path_for(config.OUTPUT_PORTS_CSV, resolution)
    plot_h3_map(
        output_csv, config.OUTPUT_CSV, ports_csv_in, output_png, config.ORIGIN_AIRPORTS,
        dpi=dpi, show_airports=show_airports, show_ports=show_ports, galton=galton, max_hours=max_hours, cmap_name=cmap_name,
        labels=labels, robinson=robinson, grid=grid, title=title, lat_limits=lat_limits, rivers=rivers,
        galton_sigma=galton_sigma, paper=paper,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-r", "--resolution", type=int, default=config.H3_RESOLUTION, help="H3-Auflösung (0-15)")
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Auflösung des PNGs")
    parser.add_argument(
        "--paper", type=parse_paper, default=None, metavar="FORMAT|BREITExHOEHE",
        help="Karte mittig auf eine Seite in diesem Format setzen (Querformat), mit Leerraum in "
             "BACKGROUND_COLOR oben/unten statt eines beliebigen, vom Inhalt abhaengigen "
             "Seitenverhaeltnisses - ohne --paper bleibt es wie bisher beim engen Zuschnitt um "
             "den tatsaechlichen Inhalt (bbox_inches=\"tight\"). Entweder ein Name "
             f"({', '.join(sorted(config.PAPER_SIZES_IN))}) oder eigene Zentimeter-Masse als "
             "BREITExHOEHE (z.B. 50x60) - Poster-Druckereien bieten oft keine DIN-Formate an.",
    )
    parser.add_argument("--airports", action="store_true", help="Flughafen-Punkte einblenden (standardmäßig aus)")
    parser.add_argument("--ports", action="store_true", help="Hafen-Punkte einblenden (standardmäßig aus)")
    parser.add_argument(
        "--galton", action="store_true",
        help="Retro-Look: geglättete, diskrete Farbbänder statt stufenloser Skala",
    )
    parser.add_argument(
        "--max-hours", type=float, default=config.GALTON_MAX_HOURS,
        help="Gesamtspanne der Farbskala in Stunden im --galton-Modus - ab hier der dunkelste "
             "Farbton statt weiterer Streckung. Gleichmaessig in zehn Baender aufgeteilt "
             "(bzw. fuenf feste bei --cmap galton5).",
    )
    parser.add_argument(
        "--galton-sigma", type=float, default=config.GALTON_SIGMA_DEG,
        help=f"Gauß-Glättungsradius in Grad im --galton-Modus (Standardabweichung, Standard {config.GALTON_SIGMA_DEG}°) - "
             "größer = weicher/verwaschener, kleiner = schärfer/näher am Rohraster",
    )
    parser.add_argument(
        "--cmap", default=None,
        help="Farbpalette. Standard: viridis_r (Standard-Matplotlib, perzeptuell gleichmaessig) - "
             "ausser mit --galton, dann Standard: galton. Weitere perzeptuell gleichmaessige "
             "Optionen: plasma_r, inferno_r, magma_r, cividis_r (oder ohne '_r' fuer umgekehrte "
             "Farbrichtung, oder jeder andere matplotlib-Colormap-Name). "
             "'galton': die zehn echten Original-Farbwerte als feste, nicht interpolierte Palette "
             "(zusammen mit --galton: zehn statt fuenf Stufen). "
             "'galton5': dieselbe Palette auf fuenf Farben reduziert, eine je Farbfamilie "
             "(zusammen mit --galton: fuenf statt zehn Stufen).",
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
             "ohne Angabe: 80,-60 (Galtons eigener Zuschnitt, unabhängig von --galton)",
    )
    parser.add_argument(
        "--rivers", action="store_true",
        help="Große Flüsse einzeichnen (Natural Earth, 110m), in derselben Strichstärke wie die Küstenlinien",
    )
    args = parser.parse_args()

    main(
        resolution=args.resolution, dpi=args.dpi, show_airports=args.airports, show_ports=args.ports, galton=args.galton,
        max_hours=args.max_hours, cmap_name=args.cmap, labels=args.labels, robinson=args.robinson,
        grid=args.grid, title=args.title, lat_limits=args.lat_limits, rivers=args.rivers,
        galton_sigma=args.galton_sigma, paper=args.paper,
    )
