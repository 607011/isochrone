"""Einmaliges Korrekturskript: erzeugt ports_corrected.csv aus ports.csv.

Etliche Zeilen in ports.csv (LINERLIB, github.com/blof/LINERLIB) haben
Longitude/Latitude vertauscht, und zwar nicht nach einem festen Muster
(manche Zeilen sind korrekt, manche nicht) - eine Distanz- oder
Wertebereichs-Heuristik allein greift zu kurz, siehe MEMO.md
("Argentia"/"Belem"-Fälle). Deshalb wird stattdessen die im Datensatz
angegebene "Country"-Spalte als Kontrolle genutzt: für beide möglichen
Lesarten (so wie im File, und vertauscht) wird per Offline-Reverse-
Geocoding das Land der Koordinate bestimmt; welche Lesart zum
angegebenen Land passt, gewinnt.

ports.csv ist ein statischer Datensatz (ändert sich nicht mehr) - die
Korrektur muss deshalb nicht bei jedem Programmlauf wiederholt werden.
Dieses Skript läuft einmalig, das Ergebnis (ports_corrected.csv) ist
eingecheckt und wird von ports_loading.py direkt gelesen. So braucht
die normale Pipeline reverse-geocoder/pycountry (native Cython-
Erweiterung, unter Windows ohne Visual-C++-Build-Tools schwierig zu
installieren, siehe MEMO.md) nur noch als optionale Dev-Abhängigkeit,
falls ports.csv sich doch einmal ändert und die Korrektur neu laufen
muss - nicht mehr für jeden `pipenv install`.
"""

import pandas as pd
import pycountry
import reverse_geocoder as rg

import config

# Fallback fuer Zeilen ohne "Country"-Angabe, wo der Land-Abgleich nicht
# greift: kein Handelshafen in ports.csv liegt südlicher als das (der
# südlichste MIT Country-Angabe ist Punta Arenas, Chile, bei ca. -53).
IMPLAUSIBLE_SOUTH_LATITUDE = -55

# pycountry kennt diese Schreibweisen aus ports.csv nicht automatisch.
_COUNTRY_ISO2_OVERRIDES = {
    "Cape Verde Island": "CV",
    "Congo. Dem. Rep. of": "CD",
    "Fiji Islands": "FJ",
    "Ivory Coast": "CI",
    "Korea. South": "KR",
    "Netherl. Antilles": "CW",
    "Reunion": "RE",
    "Russia": "RU",
    "Trinidad & Tobago": "TT",
    "Turkey": "TR",
    "U. A. E.": "AE",
}


def _country_to_iso2(name):
    if pd.isna(name):
        return None
    if name in _COUNTRY_ISO2_OVERRIDES:
        return _COUNTRY_ISO2_OVERRIDES[name]
    try:
        return pycountry.countries.lookup(name).alpha_2
    except LookupError:
        return None


def fix_ports(path) -> pd.DataFrame:
    df = pd.read_csv(path, sep="\t")

    valid = df["Longitude"].notna() & df["Latitude"].notna()
    df = df[valid].copy()
    df = df[df["Longitude"].abs() <= 180]
    df = df[df["Latitude"].abs() <= 180]

    expected_iso2 = df["Country"].map(_country_to_iso2)

    original_coords = list(zip(df["Latitude"], df["Longitude"]))
    swapped_coords = list(zip(df["Longitude"], df["Latitude"]))
    original_iso2 = [r["cc"] for r in rg.search(original_coords, verbose=False)]
    swapped_iso2 = [r["cc"] for r in rg.search(swapped_coords, verbose=False)]

    should_swap = [
        (not pd.isna(expected) and orig != expected and swapped == expected)
        or (pd.isna(expected) and (abs(lat) > 90 or lat < IMPLAUSIBLE_SOUTH_LATITUDE))
        for expected, orig, swapped, lat in zip(expected_iso2, original_iso2, swapped_iso2, df["Latitude"])
    ]
    should_swap = pd.Series(should_swap, index=df.index)
    df.loc[should_swap, ["Longitude", "Latitude"]] = df.loc[should_swap, ["Latitude", "Longitude"]].to_numpy()

    df = df.rename(columns={"UNLocode": "unlocode", "Longitude": "lon", "Latitude": "lat"})
    df = df[df["lat"].abs() <= 90]
    df = df[df["lon"].abs() <= 180]
    df = df.drop_duplicates(subset="unlocode", keep="first")
    return df[["unlocode", "name", "Country", "lat", "lon"]].reset_index(drop=True)


if __name__ == "__main__":
    corrected = fix_ports(config.PORTS_CSV)
    corrected.to_csv(config.PORTS_CORRECTED_CSV, index=False)
    print(f"{len(corrected)} Häfen korrigiert, geschrieben nach {config.PORTS_CORRECTED_CSV}")
