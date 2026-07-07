"""Kürzeste Reisezeiten von einem oder mehreren Start-Flughäfen (Dijkstra).

Mehrere Startflughäfen (z.B. die 5 Londoner Flughäfen) werden über einen
virtuellen Knoten mit Gewicht 0 angebunden, sodass jeweils der schnellste
Startpunkt automatisch gewählt wird.
"""

import networkx as nx

VIRTUAL_ORIGIN = "__ORIGIN__"


def compute_shortest_times(G: nx.DiGraph, origin_iatas, transfer_hours: float) -> dict:
    origins = [o for o in origin_iatas if o in G]
    missing = set(origin_iatas) - set(origins)
    if missing:
        print(f"Warnung: Start-Flughäfen nicht im Graphen gefunden und ignoriert: {sorted(missing)}")
    if not origins:
        raise ValueError("Keiner der angegebenen Start-Flughäfen ist im Graphen vorhanden.")

    G.add_node(VIRTUAL_ORIGIN)
    for o in origins:
        G.add_edge(VIRTUAL_ORIGIN, o, flight_hours=0.0, is_virtual=True)

    def weight(u, v, data):
        if data.get("is_virtual"):
            return 0.0
        return data["flight_hours"] + transfer_hours

    try:
        distances, paths = nx.single_source_dijkstra(G, VIRTUAL_ORIGIN, weight=weight)
    finally:
        G.remove_node(VIRTUAL_ORIGIN)

    results = {}
    for iata, hours in distances.items():
        if iata == VIRTUAL_ORIGIN:
            continue
        real_path = paths[iata][1:]  # virtuellen Startknoten aus dem Pfad entfernen
        num_edges = len(real_path) - 1
        stops = max(num_edges - 1, 0)
        results[iata] = {"hours": hours, "stops": stops, "path": real_path}

    return results
