"""Erreichbarkeitskarte ab einem beliebigen Flughafen statt London.

Nutzt exakt dieselbe Pipeline wie main.py/main_h3.py/plot_h3_map.py, nur
mit einem anderen Start-Flughafen - z.B. um zu sehen, wie die Welt von
einem Flughafen aus aussieht, der selbst erst über mehrere Umstiege ab
London erreichbar ist.
"""

import pandas as pd

import config
from data_loading import load_airports, load_routes
from graph_builder import build_graph
from h3_grid import build_grid
from land_mask import is_land
from nearest_hub import assign_travel_times, nearest_value
from plot_h3_map import plot_h3_map
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
    """Häfen + Wasserkacheln zu einer bereits berechneten Landkachel-Reisezeit.

    Unabhängig davon, wie land_result zustande kam (isotropes Kreismodell
    hier, oder das Friction-Surface-Modell in friction_map_from_airport.py) -
    ein Hafen bekommt einfach die Reisezeit seiner nächstgelegenen
    Landkachel, Wasserkacheln dann die Reisezeit des schnellsten Hafens
    im Umkreis. Siehe main_h3.py/MEMO.md für die Begründung. resolution
    muss zu der von land_result passen, sonst finden Land- und
    Wasserkacheln nicht lückenlos zusammen.
    """
    grid_df = build_grid(resolution)
    on_land = is_land(grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy())
    sea_df = grid_df[~on_land].reset_index(drop=True)

    ports_df = load_ports(config.PORTS_CSV)
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
    origin_iata, dpi=config.MAP_DPI, show_hubs=config.SHOW_HUBS,
    resolution=config.H3_RESOLUTION, galton=False,
    band_hours=config.GALTON_BAND_HOURS, cmap_name=config.COLORMAP, labels=False,
):
    travel_times_df = build_travel_times([origin_iata])
    if origin_iata not in travel_times_df["iata_code"].values:
        raise ValueError(f"{origin_iata} ist im Flugnetz nicht erreichbar/vorhanden.")

    origin_row = travel_times_df[travel_times_df["iata_code"] == origin_iata].iloc[0]
    slug = slug_for(origin_iata, origin_row["name"])
    res_suffix = "" if resolution == config.H3_RESOLUTION else f"_res{resolution}"
    galton_suffix = "_galton" if galton else ""
    labels_suffix = "_labels" if labels else ""

    h3_df, ports_df = build_h3(travel_times_df, resolution)

    travel_times_csv = f"travel_times_from_{slug}.csv"
    h3_csv = f"h3_travel_times_from_{slug}{res_suffix}.csv"
    ports_csv = f"ports_travel_times_from_{slug}{res_suffix}.csv"
    png = f"h3_travel_times_map_from_{slug}{res_suffix}{galton_suffix}{labels_suffix}.png"

    travel_times_df.to_csv(travel_times_csv, index=False)
    h3_df.to_csv(h3_csv, index=False)
    ports_df.to_csv(ports_csv, index=False)

    plot_h3_map(
        h3_csv, travel_times_csv, ports_csv, png, [origin_iata],
        origin_label=origin_row["name"], dpi=dpi, show_hubs=show_hubs, galton=galton,
        band_hours=band_hours, cmap_name=cmap_name, labels=labels,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iata", nargs="?", default="THU", help="IATA-Code des Start-Flughafens")
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Auflösung des PNGs")
    parser.add_argument("--no-hubs", action="store_true", help="Flughafen-/Hafen-Punkte ausblenden")
    parser.add_argument(
        "--galton", action="store_true",
        help="Retro-Look: geglättete, diskrete Farbbänder statt stufenloser Skala",
    )
    parser.add_argument("-r", "--resolution", type=int, default=config.H3_RESOLUTION, help="H3-Auflösung (0-15)")
    parser.add_argument(
        "--band-hours", type=float, default=config.GALTON_BAND_HOURS,
        help="Bandbreite in Stunden im --galton-Modus (0-4, 4-8, ...)",
    )
    parser.add_argument("--cmap", default=config.COLORMAP, help="Name einer matplotlib-Colormap, oder 'galton' fuer eine an das Original angelehnte Palette")
    parser.add_argument(
        "--labels", action="store_true",
        help="Kontinente und wichtigste Weltstädte beschriften, wie bei Galtons Original",
    )
    args = parser.parse_args()

    main(
        args.iata, dpi=args.dpi, show_hubs=not args.no_hubs, resolution=args.resolution, galton=args.galton,
        band_hours=args.band_hours, cmap_name=args.cmap, labels=args.labels,
    )
