"""Baut das H3-Raster und ordnet jeder Kachel eine Reisezeit ab London zu.

Reihenfolge ist wichtig:
1. Landkacheln: nächster Flughafen + Bodenzeit.
2. Häfen: einfach die Reisezeit der ihnen nächstgelegenen Landkachel -
   ein Hafen ist kein eigener Verkehrsknoten mit eigener Flughafen-Anbindung,
   er liegt ja an Land und hat damit schon eine Reisezeit aus Schritt 1.
3. Wasserkacheln: nächster Hafen (aus Schritt 2) + Seezeit.
"""

import pandas as pd

import config
from h3_grid import build_grid
from land_mask import is_land
from nearest_hub import assign_travel_times, nearest_value
from ports_loading import load_ports


def main(resolution=config.H3_RESOLUTION, output_csv=config.OUTPUT_H3_CSV, output_ports_csv=config.OUTPUT_PORTS_CSV):
    airports_df = pd.read_csv(config.OUTPUT_CSV)
    ports_df = load_ports(config.PORTS_CORRECTED_CSV)
    print(f"{len(ports_df)} Häfen mit gültigen Koordinaten geladen.")

    grid_df = build_grid(resolution)
    print(f"{len(grid_df)} H3-Kacheln bei Auflösung {resolution} erzeugt.")

    on_land = is_land(grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy())
    land_df = grid_df[on_land].reset_index(drop=True)
    sea_df = grid_df[~on_land].reset_index(drop=True)
    print(f"{len(land_df)} Landkacheln, {len(sea_df)} Wasserkacheln.")

    land_result = assign_travel_times(
        land_df, airports_df, config.MAX_AIRPORT_DISTANCE_KM, config.GROUND_SPEED_KMH,
        hub_id_col="iata_code",
    )
    land_result["hub_type"] = "airport"

    ports_df["reisezeit_stunden"] = nearest_value(ports_df, land_result, "reisezeit_stunden")
    ports_df.to_csv(output_ports_csv, index=False)
    covered_ports = ports_df["reisezeit_stunden"].notna().sum()
    print(f"{covered_ports} von {len(ports_df)} Häfen haben eine Reisezeit über die nächste Landkachel erhalten.")

    sea_result = assign_travel_times(
        sea_df, ports_df, config.MAX_PORT_DISTANCE_KM, config.SEA_SPEED_KMH,
        hub_id_col="unlocode",
    )
    sea_result["hub_type"] = "port"

    result_df = pd.concat([land_result, sea_result], ignore_index=True)

    covered = result_df["reisezeit_stunden"].notna().sum()
    print(f"{covered} von {len(result_df)} Kacheln insgesamt abgedeckt "
          f"({covered / len(result_df):.1%}); davon Land: "
          f"{land_result['reisezeit_stunden'].notna().sum()}/{len(land_result)}, "
          f"Wasser: {sea_result['reisezeit_stunden'].notna().sum()}/{len(sea_result)}.")

    result_df.to_csv(output_csv, index=False)
    print(f"Ergebnis geschrieben nach {output_csv}")


def _output_path_for(base_path, resolution):
    """Hängt bei nicht-Standard-Auflösung ein _resN an den Dateinamen an."""
    if resolution == config.H3_RESOLUTION:
        return base_path
    return base_path.with_name(f"{base_path.stem}_res{resolution}{base_path.suffix}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-r", "--resolution", type=int, default=config.H3_RESOLUTION, help="H3-Auflösung (0-15)")
    args = parser.parse_args()

    main(
        args.resolution,
        output_csv=_output_path_for(config.OUTPUT_H3_CSV, args.resolution),
        output_ports_csv=_output_path_for(config.OUTPUT_PORTS_CSV, args.resolution),
    )
