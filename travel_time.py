"""Shortest travel times from one or more origin airports (Dijkstra).

Multiple origin airports (e.g. the 5 London airports) are connected via
a virtual node, so that the fastest starting point is automatically
chosen in each case. Normally with weight 0 (the airports ARE the
origin), but origin_iatas may also be a dict {iata: entry_hours} - then
each edge gets its individual weight instead of a uniform 0, e.g. the
ground time from an arbitrary land point to this airport (see
friction_map_from_point.py). Same functional principle as the virtual
super-node in friction_surface_global.py, just in the reverse
direction: there flight time -> ground time, here ground time -> flight
time.
"""

import math

import networkx as nx

VIRTUAL_ORIGIN = "__ORIGIN__"


def compute_shortest_times(G: nx.DiGraph, origin_iatas, transfer_hours: float) -> dict:
    if isinstance(origin_iatas, dict):
        entry_hours = {o: h for o, h in origin_iatas.items() if o in G and math.isfinite(h)}
    else:
        entry_hours = {o: 0.0 for o in origin_iatas if o in G}
    missing = set(origin_iatas) - set(entry_hours)
    if missing:
        print(f"Warning: origin airports not found in the graph and ignored: {sorted(missing)}")
    if not entry_hours:
        raise ValueError("None of the given origin airports are present in the graph.")

    G.add_node(VIRTUAL_ORIGIN)
    for o, hours in entry_hours.items():
        G.add_edge(VIRTUAL_ORIGIN, o, flight_hours=hours, is_virtual=True)

    def weight(u, v, data):
        if data.get("is_virtual"):
            return data["flight_hours"]
        return data["flight_hours"] + transfer_hours

    try:
        distances, paths = nx.single_source_dijkstra(G, VIRTUAL_ORIGIN, weight=weight)
    finally:
        G.remove_node(VIRTUAL_ORIGIN)

    results = {}
    for iata, hours in distances.items():
        if iata == VIRTUAL_ORIGIN:
            continue
        real_path = paths[iata][1:]  # remove the virtual origin node from the path
        num_edges = len(real_path) - 1
        stops = max(num_edges - 1, 0)
        results[iata] = {"hours": hours, "stops": stops, "path": real_path}

    return results
