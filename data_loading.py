"""Einlesen und Bereinigen von routes.csv und airports.csv.

airports.csv liegt im klassischen OpenFlights-Format vor: keine Kopfzeile,
14 Spalten (Airport ID, Name, City, Country, IATA, ICAO, Latitude,
Longitude, Altitude, Timezone, DST, Tz-Database-Timezone, Type, Source).
"""

import pandas as pd

AIRPORT_COLUMNS = [
    "airport_id", "name", "city", "country",
    "iata", "icao", "lat", "lon", "altitude",
    "timezone", "dst", "tz_database", "type", "source",
]


def load_airports(path) -> pd.DataFrame:
    df = pd.read_csv(
        path,
        header=None,
        names=AIRPORT_COLUMNS,
        na_values=["\\N"],
        keep_default_na=True,
    )
    valid_iata = df["iata"].str.fullmatch(r"[A-Za-z]{3}", na=False)
    valid_coords = df["lat"].notna() & df["lon"].notna()
    df = df[valid_iata & valid_coords].copy()
    df["iata"] = df["iata"].str.upper()
    df = df.drop_duplicates(subset="iata", keep="first")
    return df.set_index("iata", drop=False)


def load_routes(path, airports_df: pd.DataFrame, include_codeshare: bool = True) -> pd.DataFrame:
    df = pd.read_csv(path, na_values=["\\N"], keep_default_na=True)
    df.columns = [c.strip() for c in df.columns]

    known = set(airports_df.index)
    mask = df["Source airport"].isin(known) & df["Destination airport"].isin(known)
    if not include_codeshare:
        mask &= df["Codeshare"].isna()
    df = df[mask].copy()
    df = df.drop_duplicates(subset=["Source airport", "Destination airport"])
    return df
