"""One-time correction script: generates ports_corrected.csv from ports.csv.

Quite a few rows in ports.csv (LINERLIB, github.com/blof/LINERLIB) have
longitude/latitude swapped, and not according to a fixed pattern (some
rows are correct, some aren't) - a distance or value-range heuristic
alone falls short, see MEMO.md ("Argentia"/"Belem" cases). Instead, the
"Country" column given in the dataset is used as a check: for both
possible readings (as in the file, and swapped), the coordinate's
country is determined via offline reverse geocoding; whichever reading
matches the given country wins.

ports.csv is a static dataset (no longer changes) - the correction
therefore doesn't need to be repeated on every program run. This
script runs once, the result (ports_corrected.csv) is checked in and
read directly by ports_loading.py. That way the normal pipeline only
needs reverse-geocoder/pycountry (native Cython extension, hard to
install on Windows without Visual C++ build tools, see MEMO.md) as an
optional dev dependency, in case ports.csv ever changes and the
correction has to be rerun - no longer for every `pipenv install`.
"""

import sys
from pathlib import Path

import pandas as pd
import pycountry
import reverse_geocoder as rg

# Moved to doc/ (standalone example script, not part of the web
# backend's dependency chain) - the modules below still live in the
# project root, so it needs to be on sys.path regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

# Fallback for rows without a "Country" value, where the country check
# doesn't apply: no commercial port in ports.csv lies further south than
# this (the southernmost WITH a country given is Punta Arenas, Chile, at
# about -53).
IMPLAUSIBLE_SOUTH_LATITUDE = -55

# pycountry doesn't automatically recognize these spellings from ports.csv.
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
    print(f"{len(corrected)} ports corrected, written to {config.PORTS_CORRECTED_CSV}")
