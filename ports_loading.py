"""Einlesen von ports_corrected.csv (bereits lon/lat-korrigiert).

Nur Positionsdaten werden genutzt, keine Schiffsrouten - siehe MEMO.md:
ein Hafen bekommt seine eigene Reisezeit ab London wie jede andere
Kachel (nächster Flughafen + Bodenzeit), Wasser-Kacheln bekommen dann
die Reisezeit des schnellsten Hafens im Umkreis + Seezeit.

Die eigentliche Longitude/Latitude-Korrektur (etliche Zeilen im
LINERLIB-Rohdatensatz ports.csv haben beide vertauscht) läuft nur noch
einmalig in fix_ports_coordinates.py, nicht mehr bei jedem
Programmstart - siehe dort für die Begründung und MEMO.md für die
Details der Korrektur selbst.
"""

import pandas as pd


def load_ports(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df[["unlocode", "name", "Country", "lat", "lon"]]
