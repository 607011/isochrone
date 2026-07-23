"""Building the directed airport graph with flight time as edge weight.

Transfers are deliberately NOT factored in here - that only happens in
travel_time.py, so TRANSFER_HOURS can be changed afterwards without
having to rebuild the graph.
"""

import networkx as nx
import pandas as pd

from distance import haversine_miles
from flight_time import estimate_flight_hours


def build_graph(airports_df: pd.DataFrame, routes_df: pd.DataFrame) -> nx.DiGraph:
    G = nx.DiGraph()

    for iata, row in airports_df.iterrows():
        G.add_node(iata, name=row["name"], lat=row["lat"], lon=row["lon"])

    for _, row in routes_df.iterrows():
        src, dst = row["Source airport"], row["Destination airport"]
        if src == dst:
            continue
        src_row = airports_df.loc[src]
        dst_row = airports_df.loc[dst]
        distance_miles = haversine_miles(src_row["lat"], src_row["lon"], dst_row["lat"], dst_row["lon"])
        flight_hours = estimate_flight_hours(distance_miles)
        G.add_edge(src, dst, flight_hours=flight_hours, distance_miles=distance_miles)

    return G
