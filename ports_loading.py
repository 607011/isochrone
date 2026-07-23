"""Reading ports_corrected.csv (already lon/lat-corrected).

Only position data is used, no shipping routes - see MEMO.md: a port
gets its own travel time from London like any other tile (nearest
airport + ground time), water tiles then get the travel time of the
fastest port within range + sea time.

The actual longitude/latitude correction (several rows in the
LINERLIB raw dataset ports.csv have both swapped) now only runs once
in fix_ports_coordinates.py, no longer on every program start - see
there for the rationale and MEMO.md for the details of the correction
itself.
"""

import pandas as pd


def load_ports(path) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df[["unlocode", "name", "Country", "lat", "lon"]]
