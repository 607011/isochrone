"""Builds the H3 grid and assigns each tile a travel time from London.

Order matters:
1. Land tiles: nearest airport + ground time.
2. Ports: simply the travel time of their nearest land tile - a port
   isn't its own transport hub with its own airport connection, it
   sits on land after all and so already has a travel time from step 1.
3. Water tiles: nearest port (from step 2) + sea time.
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
    print(f"{len(ports_df)} ports with valid coordinates loaded.")

    grid_df = build_grid(resolution)
    print(f"{len(grid_df)} H3 tiles generated at resolution {resolution}.")

    on_land = is_land(grid_df["lat"].to_numpy(), grid_df["lon"].to_numpy())
    land_df = grid_df[on_land].reset_index(drop=True)
    sea_df = grid_df[~on_land].reset_index(drop=True)
    print(f"{len(land_df)} land tiles, {len(sea_df)} water tiles.")

    land_result = assign_travel_times(
        land_df, airports_df, config.MAX_AIRPORT_DISTANCE_KM, config.GROUND_SPEED_KMH,
        hub_id_col="iata_code",
    )
    land_result["hub_type"] = "airport"

    ports_df["reisezeit_stunden"] = nearest_value(ports_df, land_result, "reisezeit_stunden")
    ports_df.to_csv(output_ports_csv, index=False)
    covered_ports = ports_df["reisezeit_stunden"].notna().sum()
    print(f"{covered_ports} of {len(ports_df)} ports received a travel time via the nearest land tile.")

    sea_result = assign_travel_times(
        sea_df, ports_df, config.MAX_PORT_DISTANCE_KM, config.SEA_SPEED_KMH,
        hub_id_col="unlocode",
    )
    sea_result["hub_type"] = "port"

    result_df = pd.concat([land_result, sea_result], ignore_index=True)

    covered = result_df["reisezeit_stunden"].notna().sum()
    print(f"{covered} of {len(result_df)} tiles covered in total "
          f"({covered / len(result_df):.1%}); of which land: "
          f"{land_result['reisezeit_stunden'].notna().sum()}/{len(land_result)}, "
          f"water: {sea_result['reisezeit_stunden'].notna().sum()}/{len(sea_result)}.")

    result_df.to_csv(output_csv, index=False)
    print(f"Result written to {output_csv}")


def _output_path_for(base_path, resolution):
    """Appends _resN to the filename for a non-default resolution."""
    if resolution == config.H3_RESOLUTION:
        return base_path
    return base_path.with_name(f"{base_path.stem}_res{resolution}{base_path.suffix}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-r", "--resolution", type=int, default=config.H3_RESOLUTION, help="H3 resolution (0-15)")
    args = parser.parse_args()

    main(
        args.resolution,
        output_csv=_output_path_for(config.OUTPUT_H3_CSV, args.resolution),
        output_ports_csv=_output_path_for(config.OUTPUT_PORTS_CSV, args.resolution),
    )
