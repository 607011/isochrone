"""Generates a worldwide H3 tile grid at a given resolution."""

import h3
import pandas as pd


def build_grid(resolution: int) -> pd.DataFrame:
    cells = set()
    for base_cell in h3.get_res0_cells():
        cells.update(h3.cell_to_children(base_cell, resolution))

    rows = []
    for cell in cells:
        lat, lon = h3.cell_to_latlng(cell)
        rows.append({"h3_index": cell, "lat": lat, "lon": lon})
    return pd.DataFrame(rows)
