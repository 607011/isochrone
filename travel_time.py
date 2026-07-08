"""Kürzeste Reisezeiten von einem oder mehreren Start-Flughäfen (Dijkstra).

Mehrere Startflughäfen (z.B. die 5 Londoner Flughäfen) werden über einen
virtuellen Knoten angebunden, sodass jeweils der schnellste Startpunkt
automatisch gewählt wird. Normalerweise mit Gewicht 0 (die Flughäfen SIND
der Start), aber origin_iatas darf auch ein Dict {iata: einstiegsstunden}
sein - dann bekommt jede Kante das individuelle Gewicht statt einheitlich 0,
z.B. die Bodenzeit von einem beliebigen Landpunkt bis zu diesem Flughafen
(siehe friction_map_from_point.py). Gleiches Funktionsprinzip wie der
virtuelle Superknoten in friction_surface_global.py, nur umgekehrte
Richtung: dort Flugzeit -> Bodenzeit, hier Bodenzeit -> Flugzeit.
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
        print(f"Warnung: Start-Flughäfen nicht im Graphen gefunden und ignoriert: {sorted(missing)}")
    if not entry_hours:
        raise ValueError("Keiner der angegebenen Start-Flughäfen ist im Graphen vorhanden.")

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
        real_path = paths[iata][1:]  # virtuellen Startknoten aus dem Pfad entfernen
        num_edges = len(real_path) - 1
        stops = max(num_edges - 1, 0)
        results[iata] = {"hours": hours, "stops": stops, "path": real_path}

    return results
