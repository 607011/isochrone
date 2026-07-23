"""Reachability map: fastest travel time from London to every airport worldwide."""

import csv

import config
from data_loading import load_airports, load_routes
from graph_builder import build_graph
from travel_time import compute_shortest_times


def main():
    airports_df = load_airports(config.AIRPORTS_CSV)
    routes_df = load_routes(config.ROUTES_CSV, airports_df, include_codeshare=config.INCLUDE_CODESHARE)

    print(f"{len(airports_df)} airports with valid IATA code and coordinates loaded.")
    print(f"{len(routes_df)} routes remaining after filtering.")

    G = build_graph(airports_df, routes_df)
    print(f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.")

    results = compute_shortest_times(G, config.ORIGIN_AIRPORTS, config.TRANSFER_HOURS)
    print(f"{len(results)} airports reachable from {config.ORIGIN_AIRPORTS}.")

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

    rows.sort(key=lambda r: r["reisezeit_stunden"])

    with open(config.OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "iata_code", "name", "lat", "lon", "reisezeit_stunden", "anzahl_umstiege",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Result written to {config.OUTPUT_CSV}")


if __name__ == "__main__":
    main()
