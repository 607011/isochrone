"""Draws the H3 tiles, colored by travel time from London.

Tiles without a hub within the search radius (see main_h3.py) stay
unpainted, instead of showing a made-up travel time.
"""

import os
import textwrap
from functools import lru_cache

if "SSL_CERT_FILE" not in os.environ:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()

import xml.etree.ElementTree as ET

import h3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.collections import PolyCollection
from matplotlib.colors import ListedColormap, Normalize
from matplotlib.path import Path
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.ticker import FuncFormatter
from matplotlib.transforms import Affine2D, Bbox
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
import numpy as np
import pandas as pd
from adjustText import adjust_text
from global_land_mask import globe
from PIL import Image, ImageColor
from scipy.ndimage import gaussian_filter
from sklearn.neighbors import BallTree
from svgpath2mpl import parse_path

import config

@lru_cache(maxsize=None)
def _pole_cell_indices(resolution):
    """The two H3 cells of this resolution that contain the geographic
    North/South pole - via direct H3 lookup (`latlng_to_cell(±90,
    ...)`), not by estimating from boundary vertex latitudes/longitudes.
    A latitude threshold (earlier version) fails because a true pole
    cell's boundary latitude varies enormously by resolution - at the
    coarsest resolution (0) it only reaches down to ~69°, while ordinary
    (non-polar) antimeridian cells can reach up to ~83° at finer
    resolutions. No fixed threshold sits correctly in between for all
    resolutions at once - directly identifying the actual pole cell
    sidesteps the problem entirely. `lru_cache`, since only a handful of
    different resolutions occur per map render, but very many cells are
    checked.
    """
    return {h3.latlng_to_cell(90, 0, resolution), h3.latlng_to_cell(-90, 0, resolution)}

# Coastlines and labels in anthracite instead of gray/black - closer
# to the crisp, engraved print look of Galton's original.
ANTHRACITE = "#2b2e33"
COASTLINE_LINEWIDTH = 0.7

# Spacing of the longitude/latitude grid for --grid, in degrees.
GRID_STEP_DEG = 20

# Gap between the two lines of the --galton double border, in points
# rather than axes fractions - this way the gap is exactly the same
# size in both directions, regardless of the map's (non-square) aspect
# ratio.
FRAME_GAP_PT = 3.0

# Line width of the --galton frame (both lines) - bolder than the rest
# of the linework (COASTLINE_LINEWIDTH), like the original, whose frame
# looks noticeably thicker than the coastlines.
FRAME_LINEWIDTH = 1.4

# Paper color, as an aged 1881 print would have - sits between the two
# values the user gave, rgb(220,212,183) and rgb(215,212,191).
BACKGROUND_COLOR = "#dad4bb"

# Typography in the style of old map prints: Playfair Display for the
# main heading, Libre Baskerville (bundled, see config.py) for
# place/continent names - continents bold, cities italic. Font names
# and sizes live in config.py, so they can be tuned without a code
# change, see MEMO.md.
if os.path.exists(config.PLAYFAIR_BOLD_PATH):
    fm.fontManager.addfont(config.PLAYFAIR_BOLD_PATH)
    TITLE_FONT = fm.FontProperties(fname=config.PLAYFAIR_BOLD_PATH)
else:
    TITLE_FONT = fm.FontProperties(family=config.TITLE_FONT_FALLBACK_FAMILY, weight="bold")
if os.path.exists(config.CONTINENT_FONT_PATH):
    fm.fontManager.addfont(config.CONTINENT_FONT_PATH)
    CONTINENT_FONT = fm.FontProperties(fname=config.CONTINENT_FONT_PATH)
else:
    CONTINENT_FONT = fm.FontProperties(family=config.CONTINENT_FONT_FALLBACK_FAMILY, weight="bold")
if os.path.exists(config.CITY_FONT_PATH):
    fm.fontManager.addfont(config.CITY_FONT_PATH)
    CITY_FONT = fm.FontProperties(fname=config.CITY_FONT_PATH)
else:
    CITY_FONT = fm.FontProperties(family=config.CITY_FONT_FALLBACK_FAMILY, style="italic")
if os.path.exists(config.BODY_FONT_PATH):
    fm.fontManager.addfont(config.BODY_FONT_PATH)
    BODY_FONT = fm.FontProperties(fname=config.BODY_FONT_PATH)
else:
    BODY_FONT = fm.FontProperties(family=config.BODY_FONT_FALLBACK_FAMILY)
if os.path.exists(config.EXPLANATION_TITLE_FONT_PATH):
    fm.fontManager.addfont(config.EXPLANATION_TITLE_FONT_PATH)
    EXPLANATION_TITLE_FONT = fm.FontProperties(fname=config.EXPLANATION_TITLE_FONT_PATH)
else:
    EXPLANATION_TITLE_FONT = fm.FontProperties(
        family=config.EXPLANATION_TITLE_FONT_FALLBACK_FAMILY, weight="bold",
    )

# Logo as a matplotlib Path instead of a raster image: this way it
# stays, like the rest of the graphic, losslessly vector-based up to
# the final fig.savefig(dpi=dpi) - so it scales cleanly with
# --dpi/--paper without embedding a fixed resolution. svgpath2mpl (pure
# Python) instead of an SVG rasterization library like cairosvg, which
# needs a system library (Cairo) that isn't installed everywhere -
# exactly the kind of environment-specific dependency this project has
# already deliberately avoided elsewhere (real Baskerville only on
# macOS, see Libre Baskerville instead). Only the SVG's "d" path is
# needed, no full SVG renderer - the logo is a single flat shape with
# no gradients/text.
LOGO_PATH_RAW = None
if os.path.exists(config.LOGO_SVG_PATH):
    svg_root = ET.parse(config.LOGO_SVG_PATH).getroot()
    path_elem = svg_root.find(".//{http://www.w3.org/2000/svg}path")
    if path_elem is not None:
        LOGO_PATH_RAW = parse_path(path_elem.get("d"))

# RGB values read directly off the original chart (dark/light shade
# per color), no longer just estimated by eye like the first attempt.
# Order follows the legend: green (<10 days) - yellow (10-20) -
# pink (20-30) - blue (30-40) - brown (>40 days), dark before light per
# color. Only the color mood is reproduced, not the 10-day bandwidth
# itself - that would be meaningless for our data, since the "<10
# days" category alone already covers our entire world (our maximum is
# 48h = 2 days).
GALTON_COLORS = [
    "#697f75", "#9db5ab",  # green dark/light
    "#d1c498", "#dcd4b7",  # yellow dark/light
    "#ba9ca7", "#dfc6c0",  # pink dark/light
    "#8b98a9", "#aeb5be",  # blue dark/light
    "#a48d81", "#d2bea4",  # brown dark/light
]

# --cmap galton5: a palette reduced to five colors - one per color
# family instead of the ten dark/light pairs of GALTON_COLORS. Not a
# simple "every other color" pick, but the actual single-swatch colors
# from Galton's original legend (dark green, but light
# yellow/pink/blue/brown - see the original legend image).
GALTON5_COLORS = [
    "#697f75",  # green dark
    "#dcd4b7",  # yellow light
    "#dfc6c0",  # pink light
    "#aeb5be",  # blue light
    "#d2bea4",  # brown light
]

# Rough continent-label positions for --labels - never change, hence
# hardcoded instead of derived from a dataset.
CONTINENT_LABELS = [
    ("NORTH AMERICA", -100, 45),
    ("SOUTH AMERICA", -60, -15),
    ("EUROPE", 15, 52),
    ("AFRICA", 20, 5),
    ("ASIA", 90, 50),
    ("AUSTRALIA", 135, -25),
]

# Real city names from Natural Earth (SCALERANK, see config.py) rather
# than labeling airports directly - airport names ("Heathrow") aren't
# city names ("London") anyway, and there's no ranking among ~3200 of
# them that would keep the map from turning into a jumble of letters.
def _load_city_labels(max_scalerank=config.CITY_LABEL_MAX_SCALERANK):
    path = shpreader.natural_earth(resolution="110m", category="cultural", name="populated_places")
    records = shpreader.Reader(path).records()
    return [
        (r.attributes["NAME"], r.attributes["LONGITUDE"], r.attributes["LATITUDE"])
        for r in records
        if r.attributes["SCALERANK"] <= max_scalerank
    ]


def _draw_labels(ax, city_scalerank=config.CITY_LABEL_MAX_SCALERANK):
    for name, lon, lat in CONTINENT_LABELS:
        ax.text(
            lon, lat, name, transform=ccrs.PlateCarree(), zorder=6,
            fontsize=config.CONTINENT_FONT_SIZE, color=ANTHRACITE, ha="center", va="center",
            fontproperties=CONTINENT_FONT,
        )
    city_texts = []
    for name, lon, lat in _load_city_labels(city_scalerank):
        ax.plot(
            lon, lat, marker="o", markersize=config.CITY_MARKER_SIZE, color=ANTHRACITE,
            transform=ccrs.PlateCarree(), zorder=6,
        )
        city_texts.append(ax.text(
            lon + 1, lat, name, transform=ccrs.PlateCarree(), zorder=6,
            fontsize=config.CITY_FONT_SIZE, color=ANTHRACITE, ha="left", va="center",
            fontproperties=CITY_FONT,
        ))
    # Only pushes apart city names that overlap each other (dense
    # regions like Rio/São Paulo) - coastline-aware avoidance would be a
    # bigger, separate step (see MEMO.md). Runs in the respective map
    # projection (ax.transData via the shared text transform, see
    # adjustText source), not in lon/lat, hence automatically correct
    # for both Mercator and Robinson.
    adjust_text(city_texts, ax=ax)


def _x_intersect(p1, p2, x_bound):
    """Intersection of the segment p1->p2 with the vertical line x=x_bound
    (linear interpolation in y/latitude) - helper function for _clip_polygon_x."""
    x1, y1 = p1
    x2, y2 = p2
    t = (x_bound - x1) / (x2 - x1)
    return (x_bound, y1 + t * (y2 - y1))


def _clip_polygon_x(vertices, x_bound, keep_le):
    """Sutherland-Hodgman clip of a (simple, convex) polygon at the
    vertical line x=x_bound. keep_le=True keeps the part with
    x <= x_bound, False the part with x >= x_bound. See _cell_polygon_lonlat
    for the use case (cutting antimeridian tiles into two pieces)."""
    output = []
    n = len(vertices)
    for i in range(n):
        curr = vertices[i]
        prev = vertices[i - 1]
        curr_in = (curr[0] <= x_bound) if keep_le else (curr[0] >= x_bound)
        prev_in = (prev[0] <= x_bound) if keep_le else (prev[0] >= x_bound)
        if curr_in:
            if not prev_in:
                output.append(_x_intersect(prev, curr, x_bound))
            output.append(curr)
        elif prev_in:
            output.append(_x_intersect(prev, curr, x_bound))
    return output


def _cell_polygon_lonlat(h3_index):
    """Returns a list of polygons - usually exactly one, two for tiles
    on the antimeridian (see below), none for the two true pole cells
    (not representable, see _pole_cell_indices()).
    """
    boundary = h3.cell_to_boundary(h3_index)  # tuples of (lat, lon)
    lons = [lon for _, lon in boundary]
    lats = [lat for lat, _ in boundary]
    span = max(lons) - min(lons)
    if span > 180:
        if h3_index in _pole_cell_indices(h3.get_resolution(h3_index)):
            return []
        # Tile sits on the antimeridian: do NOT (as in an earlier,
        # rolled-back attempt, see MEMO.md Phase 14zZg) shift vertices
        # to the other side via "+360" - cartopy's Mercator projection
        # silently normalizes longitudes past ±180° back into the
        # standard range when projecting, so the shift would simply
        # have no effect there and a single vertex would end up on the
        # wrong side of the map. Instead: first shift all negative
        # longitudes by 360° until a contiguous ("unwrapped") polygon
        # slightly past 180° results, then cut that at the line x=180°
        # into two real sub-polygons (Sutherland-Hodgman) - the east
        # piece stays unchanged <= 180° (already valid), the west piece
        # is shifted back by 360° after clipping and thereby also lands
        # within the valid range (<= -180° ... < 180°), never beyond
        # ±180°. Both pieces get the same value as the origin tile.
        unwrapped = [(lon + 360 if lon < 0 else lon, lat) for lon, lat in zip(lons, lats)]
        east = _clip_polygon_x(unwrapped, 180.0, keep_le=True)
        west = [(lon - 360, lat) for lon, lat in _clip_polygon_x(unwrapped, 180.0, keep_le=False)]
        return [p for p in (east, west) if len(p) >= 3]
    return [list(zip(lons, lats))]


def _project_polygons(verts_lonlat, projection):
    """Projects all tile vertices in one shot instead of polygon by polygon.

    `PolyCollection(..., transform=ccrs.PlateCarree())` lets cartopy
    reproject each polygon individually via the generic, Shapely-based
    trace algorithm (for arbitrary, possibly antimeridian-crossing
    geometries) - the dominant cost factor with hundreds of thousands
    of small hexagons (>95% of render time, see MEMO.md). But H3 tiles
    are small and (after the antimeridian correction in
    _cell_polygon_lonlat) never self-intersecting, so they don't need
    the generic trace path - a single vectorized `transform_points()`
    call over all vertices at once suffices and is orders of magnitude
    faster, because it crosses into the PROJ library once instead of
    280,000 times.
    """
    counts = [len(v) for v in verts_lonlat]
    flat_lonlat = np.array([pt for v in verts_lonlat for pt in v])
    flat_xy = projection.transform_points(ccrs.PlateCarree(), flat_lonlat[:, 0], flat_lonlat[:, 1])[:, :2]
    splits = np.cumsum(counts)[:-1]
    return np.split(flat_xy, splits)


def _nan_gaussian_filter(grid, sigma_px):
    """Gaussian filter that ignores NaN regions instead of mixing them in.

    Standard trick: replace missing values with 0, smooth both the
    values and a 0/1 validity mask, then divide one by the other - this
    way NaN cells (e.g. sea during the land pass) don't dilute the
    result, they simply drop out of the weighted average.
    mode=("nearest", "wrap"): don't mirror past the edge at the poles,
    but smooth seamlessly around the world at the date line.
    """
    valid = ~np.isnan(grid)
    filled = np.where(valid, grid, 0.0)
    smoothed_values = gaussian_filter(filled, sigma_px, mode=("nearest", "wrap"))
    smoothed_weight = gaussian_filter(valid.astype(float), sigma_px, mode=("nearest", "wrap"))
    with np.errstate(invalid="ignore", divide="ignore"):
        result = smoothed_values / smoothed_weight
    result[smoothed_weight < 1e-6] = np.nan
    return result


def _build_galton_grid(covered_df, grid_deg=config.GALTON_GRID_DEG, sigma_deg=config.GALTON_SIGMA_DEG):
    """Regular, blurred lat/lon raster for contourf instead of tiles.

    Neighbor averaging on the H3 grid itself smooths too locally to
    reproduce Galton's hand-drawn, smooth bands (see config.py).
    Instead: transfer tile values onto a regular raster via nearest
    neighbor, smooth land and water SEPARATELY with a real Gaussian
    filter (otherwise the coastline blurs away), then recombine.
    """
    lon = np.arange(-180, 180, grid_deg)
    lat = np.arange(-90, 90, grid_deg)
    lon_grid, lat_grid = np.meshgrid(lon, lat)

    tree = BallTree(np.radians(covered_df[["lat", "lon"]].to_numpy()), metric="haversine")
    _, idx = tree.query(np.radians(np.column_stack([lat_grid.ravel(), lon_grid.ravel()])), k=1)
    nearest_values = covered_df["reisezeit_stunden"].to_numpy()[idx.ravel()].reshape(lon_grid.shape)

    is_land_grid = globe.is_land(lat_grid, lon_grid)
    sigma_px = sigma_deg / grid_deg

    # globe.is_land() classifies individual pixels noticeably
    # inaccurately in places instead of switching along a clean
    # coastline - especially for small, glaciated archipelagos like
    # Svalbard, the raw mask itself looks speckled at a small scale
    # (visually confirmed with print(): isolated "land" pixels in the
    # middle of open water and vice versa), not caused by missing H3
    # coverage there. Since this mask only determines which of the two
    # SMOOTHING channels (land/sea) a raster cell's VALUE flows into -
    # not the coastline actually drawn, which still comes unchanged
    # from Natural Earth -, it's smoothed here with the same Gaussian
    # radius as the values themselves and re-thresholded at 0.5:
    # isolated misclassification speckles disappear without affecting
    # the actual map rendering. This fixes the previously visible
    # fraying in the background color inside small islands.
    is_land_grid = _nan_gaussian_filter(
        np.where(is_land_grid, 1.0, 0.0), sigma_px / 10,
    ) >= 0.5

    land_grid = np.where(is_land_grid, nearest_values, np.nan)
    sea_grid = np.where(is_land_grid, np.nan, nearest_values)
    land_smoothed = _nan_gaussian_filter(land_grid, sigma_px)
    sea_smoothed = _nan_gaussian_filter(sea_grid, sigma_px)

    values = np.where(is_land_grid, land_smoothed, sea_smoothed)
    return lon_grid, lat_grid, values


def parse_lat_limits(s):
    """CLI parser for '--lat-limits=80,-60' (north,south) -> (80.0, -60.0)."""
    north_str, south_str = s.split(",")
    north, south = float(north_str), float(south_str)
    return max(north, south), min(north, south)


def parse_paper(s):
    """CLI parser for --paper: either a name from config.PAPER_SIZES_IN
    (e.g. 'a3') or custom dimensions in centimeters as 'WIDTHxHEIGHT'
    (e.g. '50x60' or '50.0x60.0') - poster print shops often don't
    offer DIN sizes, but their own/free sizes.

    Returns the (lowercased) string unchanged instead of already
    resolved inch dimensions - the actual conversion only happens in
    _apply_paper_size(), the string also serves unchanged until then as
    the filename suffix (as already done for the DIN/US names).
    """
    key = s.strip().lower()
    if key in config.PAPER_SIZES_IN:
        return key
    width_str, height_str = key.split("x")
    float(width_str), float(height_str)  # validation only, ValueError on nonsense
    return key


def _sketch(artist, dpi):
    """Makes a line/patch artist wobble slightly "hand-drawn" instead of
    looking geometrically perfect - matplotlib's built-in mechanism
    behind plt.xkcd(), applied here deliberately only to individual
    artists rather than globally. Works on any artist with
    set_sketch_params (cartopy's FeatureArtist/Gridliner and matplotlib
    patches alike).

    scale/length are pixels per matplotlib's docs, not points (the
    comment on RETRO_SKETCH_SCALE/_LENGTH in config.py is misleading in
    that regard) - and only take effect at actual render time in
    fig.savefig(dpi=dpi), not at the intermediate fig.dpi used here
    otherwise (rcParams default, independent of the --dpi switch). A
    fixed pixel value would therefore look increasingly finer/less
    noticeable at higher --dpi (the same pixel amount corresponds to a
    smaller physical length) and coarser at lower --dpi - hence scaled
    here with dpi/config.MAP_DPI (the constants' calibration value), so
    the waviness stays visually the same size regardless of --dpi.
    randomness, by contrast, is a dimensionless scaling factor (not a
    pixel size) and stays unscaled."""
    scale_factor = dpi / config.MAP_DPI
    artist.set_sketch_params(
        scale=config.RETRO_SKETCH_SCALE * scale_factor, length=config.RETRO_SKETCH_LENGTH * scale_factor,
        randomness=config.RETRO_SKETCH_RANDOMNESS,
    )


def _draw_galton_color_legend(fig, ax, boundaries, swatch_colors, paired, dpi):
    """Color legend in the style of Galton's original (1881): a single
    brief, horizontally centered line 'Explanation of colours.' followed
    by a color swatch + range per band ('0-8h.', '8-16h.', ..., 'more
    than 48h.' for the last, open band - extend='max' in the contourf
    call gives everything beyond it the same color anyway), instead of
    a continuous color bar with its own axis and axis labels - takes up
    noticeably less height as a result. With paired=True (--cmap
    galton), every two consecutive colors (dark/light of the same color
    family, see GALTON_COLORS) are grouped as one contiguous double
    field with a shared range label, exactly like the original (five
    named color families, not ten individual shades).

    Layout in figure coordinates rather than ax.transAxes, since the
    line sits BELOW the map axes, outside its own bounding box -
    x-positions are first accumulated sequentially from x=0 based on
    the actually rendered text/swatch widths (fig.canvas.draw() +
    get_window_extent(), the same trick as for the --galton double
    border above, since text widths aren't known in advance depending
    on font/size), then shifted as a whole by the total width to appear
    centered under the map axes - the publisher line below it is
    centered separately based on its own (shorter) width.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fig_w_px, fig_h_px = fig.bbox.width, fig.bbox.height

    ax_bbox = ax.get_position()
    ax_center = (ax_bbox.x0 + ax_bbox.x1) / 2
    y = ax_bbox.y0 - 0.05
    gap = config.GALTON_LEGEND_GAP_PT * fig.dpi / 72.0
    swatch_w = config.GALTON_LEGEND_SWATCH_WIDTH_PT * fig.dpi / 72.0
    swatch_h = config.GALTON_LEGEND_SWATCH_HEIGHT_PT * fig.dpi / 72.0

    artists = []
    x = 0.0

    def place_text(s, fontproperties=TITLE_FONT, fontsize=config.GALTON_LEGEND_FONT_SIZE):
        nonlocal x
        t = fig.text(
            x, y, s, fontproperties=fontproperties, fontsize=fontsize,
            color=ANTHRACITE, va="center", ha="left",
        )
        fig.canvas.draw()
        artists.append(t)
        x += (t.get_window_extent(renderer).width + gap) / fig_w_px

    def place_swatch(color):
        nonlocal x
        r = Rectangle(
            (x, y - (swatch_h / 2) / fig_h_px), swatch_w / fig_w_px, swatch_h / fig_h_px,
            transform=fig.transFigure, facecolor=color, edgecolor=ANTHRACITE,
            linewidth=COASTLINE_LINEWIDTH, zorder=10,
        )
        _sketch(r, dpi)
        fig.add_artist(r)
        artists.append(r)
        x += swatch_w / fig_w_px

    place_text("Explanation of colours.")

    n = len(boundaries) - 1
    step = 2 if paired else 1
    n_entries = n // step
    for entry in range(n_entries):
        i = entry * step
        place_swatch(swatch_colors[i])
        if paired:
            place_swatch(swatch_colors[i + 1])
        x += gap / fig_w_px

        is_last = entry == n_entries - 1
        # Rounded to whole hours - display only, the actual band
        # boundaries (boundaries, contourf levels) stay untouched, only
        # this label is smoothed.
        lower_h = round(boundaries[i])
        upper_h = round(boundaries[i + step])
        # For the last, open band, "more than" refers to the scale's
        # upper end (max_hours), not the band's start - otherwise e.g.
        # --max-hours=40 with five bands (8h each) would show "more
        # than 32h." instead of "more than 40h.", even though the scale
        # itself extends to 40h and only beyond that (extend="max") does
        # the same color apply.
        label = f"more than {upper_h} hours." if is_last else f"{lower_h}–{upper_h}h."
        place_text(label)

    total_width = x - gap / fig_w_px
    offset = ax_center - total_width / 2
    for artist in artists:
        if isinstance(artist, Rectangle):
            artist.set_x(artist.get_x() + offset)
        else:
            px, py = artist.get_position()
            artist.set_position((px + offset, py))

    footer_fontsize = config.GALTON_LEGEND_FONT_SIZE * 2 / 3
    footer = fig.text(
        0, y - 0.028, "Published by c’t/heise Medien, 2026. Flight network: OpenFlights, 2014. Friction surface: Malaria Atlas Project, 2020. Ports: LINERLIB, 2023", fontproperties=CITY_FONT,
        fontsize=footer_fontsize, color=ANTHRACITE, va="center", ha="left",
    )
    fig.canvas.draw()
    footer_width = footer.get_window_extent(renderer).width / fig_w_px
    footer.set_position((ax_center - footer_width / 2, y - 0.028))


def _draw_galton_explanation(fig, ax, origin_label, legend, heli, jetpack):
    """Explanatory text in the style of Galton's original (1881, see
    MEMO.md) - anchored fixed at the bottom-left map corner (Phase
    14zY), not to be confused with the separate color legend below the
    map (_draw_galton_color_legend). The origin legend (the star) is
    instead stacked HERE, at the end of this function, above the box
    (`legend.set_bbox_to_anchor()`) - reversed from the earlier
    arrangement, where the box sat above the legend which stayed at its
    fixed corner. Reason: the box should always sit at the same,
    predictable spot, while the legend (whose height varies depending
    on airport/port display) flexibly aligns to it - not the other way
    around. Was briefly (Phase 14zQ) anchored in the Indian Ocean,
    because the then-wider box at this position covered Pacific islands
    (Samoa) - since the attribution wraps onto two lines (Phase 14zR)
    the box is narrow enough to fit on the left of the map again
    without extending there.

    Unlike Galton's blanket "showing the shortest number of days
    journey from London by the quickest through routes and using such
    further conveyances as are available without unreasonable cost",
    the text describes exactly what this model actually computes: a
    combined flight/ground/sea travel time from the chosen origin point
    (not necessarily London), in hours instead of days (our maximum is
    around 48h instead of Galton's several weeks), as a strict Dijkstra
    minimum instead of a judgment call "without unreasonable cost". The
    only leniency assumption actually present in the model is
    TRANSFER_HOURS per transfer - this stands in for Galton's vague
    "local preparations have been made and other circumstances are
    favourable".

    All lines are centered on a shared vertical axis, except for the
    body paragraph: matplotlib has no true justified text (that would
    need word-by-word placement with dynamically computed word
    spacing) - the paragraph therefore stays left-aligned per line, but
    as a whole (based on its widest line) centered on the same vertical
    axis, instead of fully left-aligned as before. The vertical axis
    itself is positioned so that the BACKGROUND of the box (not just
    the text - see the pad_px shift below) as a whole aligns flush left
    with the map corner where the legend originally sat (before being
    moved, see below) - otherwise the box would extend past that left
    edge into the degree numbers at the map border (text block), or
    even reach the map frame itself (background, whose own padding
    would otherwise extend beyond that).

    Positioning as for the color legend: text is first created
    invisibly at placeholder positions, to know the actually rendered
    widths/heights (fig.canvas.draw() + get_window_extent(), since
    these depend on font/size), then moved to the final position. The
    lines are stacked bottom to top in reverse reading order
    (attribution first, title last), since each new line appears above
    the previous one.
    """
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fig_w_px, fig_h_px = fig.bbox.width, fig.bbox.height
    legend_bbox = legend.get_window_extent(renderer)

    body_from = f"from {origin_label} " if origin_label else ""
    body = (
        f"showing the shortest number of hours’ journey {body_from}"
        "by the quickest available routes, combining scheduled flight "
        "connections with realistic road- and terrain-following travel "
        "time to and from the airport, and shipping time across open "
        f"water. Airport transfers are assumed to take {config.TRANSFER_HOURS:g} "
        "hours each; it is supposed that no other delays occur."
    )
    if heli or jetpack:
        body += (
            " Where a helicopter or jetpack is used for departure, its "
            "higher speed and limited range are accounted for."
        )
    body_lines = textwrap.wrap(body, width=config.EXPLANATION_BODY_WRAP_CHARS)

    # Every line (body paragraph AND the single-line elements) is first
    # created at placeholder position (0, 0), just to know its rendered
    # width - the overall widest one determines the vertical axis so
    # that the box as a whole aligns flush left with the legend (see
    # docstring), instead of hitting its center.
    def measure(text_str, fontproperties, fontsize):
        t = fig.text(
            0, 0, text_str, fontproperties=fontproperties, fontsize=fontsize,
            color=ANTHRACITE, va="bottom", ha="left", zorder=6,
        )
        fig.canvas.draw()
        return t, t.get_window_extent(renderer).width

    body_artists = []
    max_body_width_px = 0.0
    for line_str in body_lines:
        t, width_px = measure(line_str, BODY_FONT, config.EXPLANATION_BODY_FONT_SIZE)
        max_body_width_px = max(max_body_width_px, width_px)
        body_artists.append(t)

    title_artist, title_width_px = measure("ISOCHRONE CHART", EXPLANATION_TITLE_FONT, config.EXPLANATION_TITLE_FONT_SIZE)
    subtitle_artist, subtitle_width_px = measure("FOR TRAVELLERS,", CONTINENT_FONT, config.EXPLANATION_SUBTITLE_FONT_SIZE)
    attr1_artist, attr1_width_px = measure("In the manner of", CONTINENT_FONT, config.EXPLANATION_BODY_FONT_SIZE)
    attr2_artist, attr2_width_px = measure(
        "Francis Galton, F.R.S. (1881).", CONTINENT_FONT, config.EXPLANATION_BODY_FONT_SIZE,
    )

    max_width_px = max(max_body_width_px, title_width_px, subtitle_width_px, attr1_width_px, attr2_width_px)
    # The text block itself starts pad_px AFTER legend_bbox.x0 - the
    # background (bg_rect below) is expanded outward again by the same
    # pad_px, so its visible left edge ends up exactly at
    # legend_bbox.x0, instead of extending pad_px beyond that toward
    # the map edge.
    pad_px = config.EXPLANATION_BG_PAD_PT * fig.dpi / 72.0
    center_x_px = legend_bbox.x0 + pad_px + max_width_px / 2
    para_x = (center_x_px - max_body_width_px / 2) / fig_w_px

    x_center = center_x_px / fig_w_px
    # Starts at the fixed map corner (legend_bbox.y0, where the legend
    # originally sat via loc="lower left") instead of above the legend
    # - the box now takes over its corner position, see docstring. Like
    # for the left edge: +pad_px, so the background lands exactly on
    # legend_bbox.y0 again after its own pad_px expansion.
    y = (legend_bbox.y0 + pad_px) / fig_h_px
    line_gap_px = 2.0 * fig.dpi / 72.0
    para_gap_px = 4.0 * fig.dpi / 72.0
    all_artists = list(body_artists) + [title_artist, subtitle_artist, attr1_artist, attr2_artist]

    def place_centered(artist, extra_gap_px=0.0):
        nonlocal y
        artist.set_position((x_center, y))
        artist.set_ha("center")
        fig.canvas.draw()
        y += (artist.get_window_extent(renderer).height + line_gap_px + extra_gap_px) / fig_h_px

    # Bold instead of italic (CONTINENT_FONT instead of CITY_FONT) -
    # reads more like a signature line. Wrapped onto two lines instead
    # of one long one - makes the box narrower overall, since this line
    # would otherwise be the widest in the whole block (wider than any
    # paragraph line).
    place_centered(attr2_artist)
    place_centered(attr1_artist)

    for i, t in enumerate(reversed(body_artists)):
        is_top_line = i == len(body_artists) - 1
        t.set_position((para_x, y))
        fig.canvas.draw()
        extra_gap_px = para_gap_px if is_top_line else 0.0
        y += (t.get_window_extent(renderer).height + line_gap_px + extra_gap_px) / fig_h_px

    # "FOR TRAVELLERS," with serifs (CONTINENT_FONT) instead of the
    # sans-serif title grotesque - like the original, where only the
    # main heading is sans-serif.
    place_centered(subtitle_artist, extra_gap_px=para_gap_px)
    place_centered(title_artist)

    # Lighter background for better contrast against the (partly dark)
    # map - a patch behind all text elements, sized from their combined
    # bounding box.
    fig.canvas.draw()
    bg_bbox = None
    for artist in all_artists:
        artist_bbox = artist.get_window_extent(renderer)
        bg_bbox = artist_bbox if bg_bbox is None else Bbox.union([bg_bbox, artist_bbox])
    bg_px = Bbox.from_extents(
        bg_bbox.x0 - pad_px, bg_bbox.y0 - pad_px, bg_bbox.x1 + pad_px, bg_bbox.y1 + pad_px,
    )
    bg_axes = bg_px.transformed(ax.transAxes.inverted())
    bg_rect = Rectangle(
        (bg_axes.x0, bg_axes.y0), bg_axes.width, bg_axes.height,
        transform=ax.transAxes, facecolor=config.EXPLANATION_BG_COLOR, edgecolor="none",
        alpha=config.EXPLANATION_BG_ALPHA, zorder=5, clip_on=False,
    )
    ax.add_patch(bg_rect)

    # Now shift the origin legend above the box, instead of leaving it
    # at its original corner position - loc="lower left" stays active,
    # only the anchor point moves to the box's top edge, so the legend
    # still docks there with its own bottom-left corner (set_bbox_to_anchor
    # also accepts just a point instead of a full bbox, interpreted via loc).
    gap_axes = config.GALTON_LEGEND_GAP_PT * fig.dpi / 72.0 / ax.get_window_extent(renderer).height
    legend.set_bbox_to_anchor((bg_axes.x0, bg_axes.y1 + gap_axes), transform=ax.transAxes)
    fig.canvas.draw()


def _apply_retro_noise(png_path, strength=config.RETRO_NOISE_STRENGTH, seed=0):
    """Aged-paper noise as post-processing over the finished PNG -
    coarse-grained, upscaled blotches (foxing-like paper marbling) plus
    fine pixel noise (grain texture), additively mixed and added onto
    the image. Much simpler than building noise into the rendering
    itself, and independent of projection/resolution/DPI - acts on the
    already fully composed image (map + legend + title)."""
    img = Image.open(png_path).convert("RGB")
    w, h = img.size
    rng = np.random.default_rng(seed)
    coarse = rng.normal(0, 1, size=(h // 10 + 1, w // 10 + 1)).astype(np.float32)
    coarse = np.array(Image.fromarray(coarse, mode="F").resize((w, h), Image.BILINEAR))
    fine = rng.normal(0, 1, size=(h, w)).astype(np.float32)
    grain = 0.6 * coarse + 0.4 * fine
    grain = grain / (np.abs(grain).max() + 1e-9)
    arr = np.asarray(img, dtype=np.float32)
    arr += grain[..., None] * strength * 255
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    Image.fromarray(arr).save(png_path)


def _apply_paper_size(png_path, paper, dpi):
    """Places the finished rendered (tightly cropped via
    bbox_inches="tight") map centered on a page in the chosen paper
    size (--paper), instead of distorting or cropping it - blank space
    top and bottom in BACKGROUND_COLOR, since our maps are noticeably
    wider than tall, while standard pages (DIN/US) have a much
    narrower aspect ratio. Pure raster post-processing over the
    finished PNG, like _apply_retro_noise already does - avoids
    touching the existing, already finely tuned
    figsize/bbox_inches="tight" logic, which automatically adapts to
    all content (title, legend, explanation box, frame), regardless of
    which flags are set.

    Scales the cropped image to the full paper width for this
    (landscape, since the map itself is wider than tall) - a slight
    up-/down-scaling relative to the organically grown original width
    is unavoidable once an exact paper size is enforced, but not
    visually noticeable at the resolutions typically used here. Called
    before _apply_retro_noise (see plot_h3_map()), so the paper grain
    also covers the newly added blank space, instead of staying
    unnaturally smooth there.

    paper (validated via parse_paper()) is either a name from
    config.PAPER_SIZES_IN or custom centimeter dimensions as
    'WIDTHxHEIGHT' - poster print shops often don't offer DIN sizes.
    """
    if paper in config.PAPER_SIZES_IN:
        width_in, height_in = config.PAPER_SIZES_IN[paper]
    else:
        width_cm, height_cm = (float(v) for v in paper.split("x"))
        width_in, height_in = width_cm / 2.54, height_cm / 2.54
    page_w_px, page_h_px = round(max(width_in, height_in) * dpi), round(min(width_in, height_in) * dpi)

    img = Image.open(png_path).convert("RGB")
    scale = page_w_px / img.width
    resized = img.resize((page_w_px, round(img.height * scale)), Image.LANCZOS)

    bg_rgb = ImageColor.getrgb(BACKGROUND_COLOR)
    page = Image.new("RGB", (page_w_px, page_h_px), bg_rgb)
    paste_y = max(0, (page_h_px - resized.height) // 2)
    page.paste(resized, (0, paste_y))
    page.save(png_path)


def _draw_logo(fig, ax):
    """Places the c't logo (LOGO_PATH_RAW, parsed from assets/ct-logo.svg)
    at the bottom-right of EVERY map - regardless of --galton, unlike
    the signature line (_draw_credits), which requires the map frame
    that only exists there.

    Size is based on the font of the "Published by..." line
    (config.GALTON_LEGEND_FONT_SIZE * 2/3), even though that line
    itself only exists under --galton - the user's request was
    "roughly the height of the letters" of that line, not its actual
    position.

    Position: bottom-right corner of all content so far
    (fig.get_tightbbox(), the same bbox that bbox_inches="tight" uses
    for cropping when saving anyway) - this way it works consistently
    with and without --galton/--title/--labels/etc., without depending
    on the different layout elements of those modes. Must therefore be
    called last before fig.savefig(), otherwise the measured bbox would
    still be incomplete.

    Positioning in figure fractions (fig.transFigure) instead of via
    fig.dpi_scale_trans: path vertices are converted to pixels and then
    to fractions IN ADVANCE (via .transformed()), instead of giving the
    patch itself a transform composed from fig.dpi_scale_trans - the
    latter did yield a correct get_window_extent() preview, but the
    finished PNG cropped with bbox_inches="tight" then showed the logo
    patch either not at all or in a completely wrong place (see
    MEMO.md). fig.transFigure with coordinates pre-converted to
    pixels/fractions is the same proven approach as for the color
    legend and the signature lines above.
    """
    if LOGO_PATH_RAW is None:
        return
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    fig_w_px, fig_h_px = fig.bbox.width, fig.bbox.height
    content_bbox = fig.get_tightbbox(renderer)  # in inches
    content_x1_px = content_bbox.x1 * fig.dpi
    content_y0_px = content_bbox.y0 * fig.dpi

    target_height_px = (config.GALTON_LEGEND_FONT_SIZE * 2 / 3) * fig.dpi / 72.0
    logo_bbox = LOGO_PATH_RAW.get_extents()
    scale = target_height_px / logo_bbox.height

    margin_px = config.LOGO_GAP_PT * fig.dpi / 72.0
    # SVG y grows downward, matplotlib y grows upward - hence
    # scale(scale, -scale) instead of just scale(scale), to mirror the
    # logo instead of placing it upside down.
    affine = Affine2D().scale(scale, -scale)
    scaled_bbox = LOGO_PATH_RAW.transformed(affine).get_extents()
    target_x1_px = content_x1_px - margin_px
    target_y0_px = content_y0_px + margin_px
    affine = affine.translate(target_x1_px - scaled_bbox.x1, target_y0_px - scaled_bbox.y0)

    final_path = LOGO_PATH_RAW.transformed(affine)
    final_path = Path(final_path.vertices / [fig_w_px, fig_h_px], final_path.codes)

    patch = PathPatch(
        final_path, transform=fig.transFigure,
        facecolor=ANTHRACITE, edgecolor="none", zorder=10, clip_on=False,
    )
    fig.add_artist(patch)



def plot_h3_map(
    h3_csv_path, travel_times_csv_path, ports_csv_path, png_path, origin_iatas,
    origin_label="London", dpi=config.MAP_DPI, show_airports=config.SHOW_AIRPORTS,
    show_ports=config.SHOW_PORTS, galton=False,
    max_hours=config.GALTON_MAX_HOURS, cmap_name=None, labels=False, robinson=False,
    grid=False, title=False, lat_limits=None, origin_points=None, rivers=False,
    galton_sigma=config.GALTON_SIGMA_DEG, heli=False, jetpack=False, paper=None,
    city_scalerank=config.CITY_LABEL_MAX_SCALERANK,
):
    # --galton implies --rivers/--grid/--labels - the retro look shows
    # rivers, the graticule, and the continent/city labels anyway like
    # the original, requiring them separately would just be an
    # unnecessary extra flag.
    rivers = rivers or galton
    grid = grid or galton
    labels = labels or galton
    # --galton also implies --cmap galton (instead of config.COLORMAP),
    # unless --cmap was explicitly set - the retro look should show
    # Galton's real original colors, not viridis_r.
    cmap_name = cmap_name or ("galton" if galton else config.COLORMAP)

    # low_memory=False: hub_id is partly NaN (land tiles from the
    # friction-surface path have none, see friction_map_from_point.py)
    # and partly string (ports) - pandas' chunk-wise type detection
    # otherwise warns about this mixed column, which isn't used here anyway.
    df = pd.read_csv(h3_csv_path, low_memory=False)
    covered = df[df["reisezeit_stunden"].notna()].copy()

    airports_df = pd.read_csv(travel_times_csv_path)
    ports_df = pd.read_csv(ports_csv_path)
    # origin_points: for origin points that aren't airports (see
    # friction_map_from_point.py) - directly passed (lat, lon) pairs
    # instead of a lookup in airports_df by IATA code.
    if origin_points is not None:
        origin_lats = [lat for lat, lon in origin_points]
        origin_lons = [lon for lat, lon in origin_points]
    else:
        origins = airports_df[airports_df["iata_code"].isin(origin_iatas)]
        origin_lats = origins["lat"]
        origin_lons = origins["lon"]

    fig = plt.figure(figsize=(16, 9))
    fig.patch.set_facecolor(BACKGROUND_COLOR)
    if robinson:
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.Robinson())
        ax.set_global()
    else:
        # Like Galton's original (1881) - Mercator can't represent the
        # poles (distance to the pole becomes infinite), so limit to a
        # latitude range instead of ax.set_global(). Also explains the
        # original effect where Greenland/Svalbard look
        # disproportionately large - a known Mercator distortion, not a
        # bug. Defaults to Galton's own crop (80°N/60°S, asymmetric -
        # the map extended further north than south), independent of
        # --galton - not just a stylistic quirk of the retro look, but
        # also practical: cuts off most of the already heavily
        # distorted, not very informative Antarctica.
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.Mercator())
        lat_max, lat_min = lat_limits if lat_limits is not None else (80, -60)
        # -180/180 exactly makes cartopy's Mercator edge computation
        # run into NaN, hence a tiny inset.
        ax.set_extent([-179.9, 179.9, lat_min, lat_max], crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.LAND, facecolor="#f0f0e8", zorder=0)
    ax.add_feature(cfeature.OCEAN, facecolor="#d9e8f5", zorder=0)
    coast = ax.coastlines(linewidth=COASTLINE_LINEWIDTH, color=ANTHRACITE, zorder=2)
    if galton:
        _sketch(coast, dpi)

    if rivers:
        # Natural Earth layer for the major, globally significant rivers
        # (110m resolution, like the other cfeature layers) - at the
        # same line width as the coastlines, like Galton's original,
        # which also only shows the prominent rivers.
        river_feature = ax.add_feature(cfeature.RIVERS, edgecolor=ANTHRACITE, linewidth=COASTLINE_LINEWIDTH, zorder=2)
        if galton:
            _sketch(river_feature, dpi)

    if grid or galton:
        # In --galton mode, like the 1881 original, the degree numbers
        # should sit on the outer edges, regardless of whether the
        # inner lines (--grid) are visible - hence lines shown only for
        # --grid (alpha=0 instead of omitting, so the ticks/labels still
        # appear in the right places), labels only for --galton.
        # Cartopy's gridliner labels only work with rectangular
        # projections (Mercator), not with Robinson.
        draw_labels = galton and not robinson
        # ylocs: range(-90, 91, ...) would NOT start at the equator,
        # since 90 isn't a multiple of GRID_STEP_DEG - the steps would
        # then be offset (e.g. at 20°: -90,-70,...,-10,10,...,90, so
        # never 0). Instead, count symmetrically around the equator
        # starting from the largest multiple of GRID_STEP_DEG <= 90, so
        # that 0° is always its own grid point, like the original.
        lat_max = (90 // GRID_STEP_DEG) * GRID_STEP_DEG
        gl = ax.gridlines(
            xlocs=range(-180, 181, GRID_STEP_DEG), ylocs=range(-lat_max, lat_max + 1, GRID_STEP_DEG),
            linewidth=COASTLINE_LINEWIDTH, color=ANTHRACITE, linestyle="-",
            alpha=0.8 if grid else 0, zorder=2, draw_labels=draw_labels,
        )
        if draw_labels:
            # Like the original: degree numbers on all four sides, not
            # just top/side - but only the bare number, without °/N/E/S/W.
            gl.top_labels = True
            gl.bottom_labels = True
            gl.left_labels = True
            gl.right_labels = True
            gl.xlabel_style = {"color": ANTHRACITE, "fontsize": 8, "fontproperties": CITY_FONT}
            gl.ylabel_style = {"color": ANTHRACITE, "fontsize": 8, "fontproperties": CITY_FONT}
            # Like the original: no signs, west/south are recognizable
            # by position (edge), not by a minus before the number.
            plain_formatter = FuncFormatter(lambda v, pos: f"{abs(v):g}")
            gl.xformatter = plain_formatter
            gl.yformatter = plain_formatter

    if galton:
        # Three lines in total, like the original: a thin double border
        # right at the map (spine + a Rectangle sitting just inside it,
        # both COASTLINE_LINEWIDTH), plus a noticeably bolder outer line
        # (FRAME_LINEWIDTH) that also encloses the degree numbers at
        # the edge instead of leaving them floating outside unbounded.
        ax.spines["geo"].set_edgecolor(ANTHRACITE)
        ax.spines["geo"].set_linewidth(COASTLINE_LINEWIDTH)
        _sketch(ax.spines["geo"], dpi)
        fig.canvas.draw()
        # set_sketch_params() on the gridliner object itself has no
        # effect - the lines actually drawn are separate LineCollection
        # artists (xline_artists/yline_artists), which only come into
        # existence on the first canvas.draw() (see above) and are
        # therefore only reachable here. gl always exists at this
        # point, since galton (this block's condition) implies the
        # condition of the gridlines() block above (grid or galton).
        for line_artist in list(gl.xline_artists) + list(gl.yline_artists):
            _sketch(line_artist, dpi)
        renderer = fig.canvas.get_renderer()

        # Inner frame: just inside the spine, produces the thin double
        # rule right at the map.
        bbox_px = ax.get_window_extent(renderer)
        gap_px = FRAME_GAP_PT * fig.dpi / 72.0
        inner_px = Bbox.from_extents(
            bbox_px.x0 + gap_px, bbox_px.y0 + gap_px, bbox_px.x1 - gap_px, bbox_px.y1 - gap_px,
        )
        inner_axes = inner_px.transformed(ax.transAxes.inverted())
        inner_rect = Rectangle(
            (inner_axes.x0, inner_axes.y0), inner_axes.width, inner_axes.height,
            transform=ax.transAxes, fill=False, edgecolor=ANTHRACITE, linewidth=COASTLINE_LINEWIDTH, zorder=5,
        )
        _sketch(inner_rect, dpi)
        ax.add_patch(inner_rect)

        # Outer frame: encloses not just the map axes itself, but also
        # the degree numbers at its edge - their actual extent is only
        # known after rendering (font size, character count), hence
        # determined via bounding-box union of all label artists
        # instead of an estimated fixed margin.
        for label_artist in gl.label_artists:
            bbox_px = Bbox.union([bbox_px, label_artist.get_window_extent(renderer)])
        outer_px = Bbox.from_extents(
            bbox_px.x0 - gap_px, bbox_px.y0 - gap_px, bbox_px.x1 + gap_px, bbox_px.y1 + gap_px,
        )
        outer_axes = outer_px.transformed(ax.transAxes.inverted())
        outer_rect = Rectangle(
            (outer_axes.x0, outer_axes.y0), outer_axes.width, outer_axes.height,
            transform=ax.transAxes, fill=False, edgecolor=ANTHRACITE, linewidth=FRAME_LINEWIDTH, zorder=5,
            clip_on=False,
        )
        _sketch(outer_rect, dpi)
        ax.add_patch(outer_rect)

        # Signature line like the original, which immortalizes itself
        # there with the cartographer ("H. Sharbau, F.G.S. del.",
        # bottom-left) and lithographer ("E. Weller. lith.",
        # bottom-right) - directly below the outer frame, converted in
        # axes fractions relative to the axes height (not the figure
        # height), since outer_axes is already in ax.transAxes coordinates.
        ax_height_px = ax.get_window_extent(renderer).height
        gap_axes = (config.CREDITS_GAP_PT * fig.dpi / 72.0) / ax_height_px
        credits_y = outer_axes.y0 - gap_axes
        ax.text(
            outer_axes.x0, credits_y, "O. Lau, ed., c’t", transform=ax.transAxes,
            fontproperties=CITY_FONT, fontsize=config.CREDITS_FONT_SIZE, color=ANTHRACITE,
            va="top", ha="left", zorder=6, clip_on=False,
        )
        ax.text(
            outer_axes.x1, credits_y, "Claude, gen. AI, Anthropic", transform=ax.transAxes,
            fontproperties=CITY_FONT, fontsize=config.CREDITS_FONT_SIZE, color=ANTHRACITE,
            va="top", ha="right", zorder=6, clip_on=False,
        )

    # Like Galton's original: beyond max_hours (--max-hours) the
    # darkest shade is assigned, instead of stretching the scale
    # linearly to the actual maximum (several days of sea time in the
    # middle of the ocean).
    if cmap_name == "galton5":
        # ListedColormap instead of interpolation: fixed colors, no
        # in-between tones - a direct palette instead of control points
        # for an interpolation.
        cmap = ListedColormap(GALTON5_COLORS)
    elif cmap_name == "galton":
        cmap = ListedColormap(GALTON_COLORS)
    else:
        cmap = matplotlib.colormaps[cmap_name].copy()

    if galton:
        # contourf instead of tile mosaic: see _build_galton_grid for
        # the rationale (H3 neighbor averaging smooths too locally to
        # reproduce Galton's hand-drawn bands).
        lon_grid, lat_grid, galton_values = _build_galton_grid(covered, sigma_deg=galton_sigma)
        # Number of bands follows the palette size: five equal-width
        # levels for --cmap galton5, otherwise ten (--cmap galton or
        # any other colormap in --galton mode) - one fixed level per
        # palette color, no separate CLI switch for the band count.
        n_bands = len(GALTON5_COLORS) if cmap_name == "galton5" else len(GALTON_COLORS)
        boundaries = np.linspace(0, max_hours, n_bands + 1)
        mappable = ax.contourf(
            lon_grid, lat_grid, galton_values, levels=boundaries, cmap=cmap, extend="max",
            transform=ccrs.PlateCarree(), zorder=1,
        )
        n_dropped = 0
    else:
        polygon_lists = [_cell_polygon_lonlat(h) for h in covered["h3_index"]]
        raw_values = covered["reisezeit_stunden"].to_numpy()
        # Usually one polygon per tile, two for antimeridian tiles (see
        # _cell_polygon_lonlat) - their value duplicated accordingly,
        # none for pole tiles (n_dropped).
        verts_lonlat = [p for polys in polygon_lists for p in polys]
        values = np.array([v for polys, v in zip(polygon_lists, raw_values) for _ in polys])
        n_dropped = sum(1 for polys in polygon_lists if not polys)
        verts = _project_polygons(verts_lonlat, ax.projection)

        norm = Normalize(vmin=0, vmax=max_hours, clip=False)
        mappable = PolyCollection(
            verts, array=values, cmap=cmap, norm=norm,
            edgecolors="none", antialiased=False, zorder=1,
        )
        ax.add_collection(mappable)

    if show_airports:
        ax.scatter(
            airports_df["lon"], airports_df["lat"], c="#ff9d00", marker="o", s=4,
            linewidths=0, alpha=0.8, transform=ccrs.PlateCarree(), zorder=3, label="Airport",
        )
    if show_ports:
        ax.scatter(
            ports_df["lon"], ports_df["lat"], c="#ff00c8", marker="o", s=4,
            linewidths=0, alpha=0.8, transform=ccrs.PlateCarree(), zorder=3, label="Port",
        )
    # No origin_label (--label omitted) means no label at all, not a
    # coordinate fallback (see friction_map_from_point.py) - "_nolegend_"
    # is matplotlib's own convention for "don't give this artist a
    # legend entry" (an empty string "" is ALSO treated as "no entry",
    # so that doesn't work here). Under --galton the star still needs
    # *a* legend entry regardless, even a blank-looking one, since
    # _draw_galton_explanation below anchors itself to the legend's own
    # bounding box - a single space keeps that entry (and thus the
    # anchor) without rendering any visible text.
    origin_legend_label = origin_label or (" " if galton else "_nolegend_")
    ax.scatter(
        origin_lons, origin_lats, c="red", marker="*", s=200,
        transform=ccrs.PlateCarree(), zorder=9, label=origin_legend_label,
    )

    if galton:
        # Like the original: discrete color swatches with range labels
        # instead of a continuous color bar, see _draw_galton_color_legend().
        n_bands = len(boundaries) - 1
        if cmap_name == "galton5":
            swatch_colors = GALTON5_COLORS
        elif cmap_name == "galton":
            swatch_colors = GALTON_COLORS
        else:
            swatch_colors = [cmap((i + 0.5) / n_bands) for i in range(n_bands)]
        _draw_galton_color_legend(fig, ax, boundaries, swatch_colors, paired=cmap_name == "galton", dpi=dpi)
    else:
        cbar = fig.colorbar(mappable, ax=ax, orientation="horizontal", pad=0.05, shrink=0.6, extend="max")
        cbar.set_label(f"Travel time from {origin_label} in hours" if origin_label else "Travel time in hours")

    if title:
        resolution = h3.get_resolution(covered["h3_index"].iloc[0]) if len(covered) else "?"
        if galton:
            detail = f"{n_bands} fixed levels, smoothed (Gaussian radius {galton_sigma}°)"
        else:
            detail = f"{len(covered)}/{len(df)} tiles covered, {n_dropped} pole tiles not representable"
        title_from = f"from {origin_label} " if origin_label else ""
        ax.set_title(
            f"Reachability {title_from}— H3 grid res. {resolution}, land+sea ({detail})",
            fontproperties=TITLE_FONT, fontsize=config.TITLE_FONT_SIZE, color=ANTHRACITE,
        )
    # Skip an empty legend (matplotlib would otherwise warn "no artists
    # with labels found") - only happens with no --label, --airports, or
    # --ports, and not --galton (which always needs one, see above).
    legend = None
    if show_airports or show_ports or origin_label or galton:
        legend = ax.legend(loc="lower left", markerscale=2)
        if galton:
            for text in legend.get_texts():
                text.set_fontproperties(TITLE_FONT)
        # Only the star should appear smaller in the legend than on the map
        # (there it stays deliberately eye-catchingly large) - hence
        # shrinking just this one handle after the legend is auto-created,
        # instead of adjusting the scatter() call itself. scatter() sizes
        # are areas, not diameters - divide by 4 rather than 2, so the star
        # looks visually (in diameter) half as big.
        for handle, text in zip(legend.legend_handles, legend.get_texts()):
            if text.get_text() == origin_legend_label:
                handle.set_sizes(handle.get_sizes() / 4)

    if galton:
        _draw_galton_explanation(fig, ax, origin_label, legend, heli, jetpack)

    if labels:
        _draw_labels(ax, city_scalerank)

    _draw_logo(fig, ax)

    fig.savefig(png_path, dpi=dpi, bbox_inches="tight", facecolor=BACKGROUND_COLOR)
    if paper:
        _apply_paper_size(png_path, paper, dpi)
    if galton:
        _apply_retro_noise(png_path)
    print(f"Map saved as {png_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=config.MAP_DPI, help="Resolution of the PNG")
    parser.add_argument(
        "--paper", type=parse_paper, default=None,
        metavar="FORMAT|WIDTHxHEIGHT",
        help="Center the map on a page of this size (landscape), with blank space in "
             "BACKGROUND_COLOR top/bottom instead of an arbitrary, content-dependent "
             "aspect ratio - without --paper it stays as before, tightly cropped around "
             "the actual content (bbox_inches=\"tight\"). Either a name "
             f"({', '.join(sorted(config.PAPER_SIZES_IN))}) or custom centimeter dimensions as "
             "WIDTHxHEIGHT (e.g. 50x60) - poster print shops often don't offer DIN sizes.",
    )
    parser.add_argument("--airports", action="store_true", help="Show airport points (off by default)")
    parser.add_argument("--ports", action="store_true", help="Show port points (off by default)")
    parser.add_argument(
        "--galton", action="store_true",
        help="Retro look: smoothed, discrete color bands instead of a continuous scale",
    )
    parser.add_argument(
        "--max-hours", type=float, default=config.GALTON_MAX_HOURS,
        help="Total span of the color scale in hours - beyond this the darkest shade "
             "instead of further stretching. Applies to both rendering modes; under "
             "--galton additionally split evenly into ten bands (or five fixed ones "
             "with --cmap galton5).",
    )
    parser.add_argument(
        "--galton-sigma", type=float, default=config.GALTON_SIGMA_DEG,
        help=f"Gaussian smoothing radius in degrees in --galton mode (standard deviation, default {config.GALTON_SIGMA_DEG}°) - "
             "larger = softer/blurrier, smaller = sharper/closer to the raw raster",
    )
    parser.add_argument(
        "--cmap", default=None,
        help="Color palette. Default: viridis_r (standard matplotlib, perceptually uniform) - "
             "except with --galton, then default: galton. Other perceptually uniform "
             "options: plasma_r, inferno_r, magma_r, cividis_r (or without '_r' for the "
             "reversed color direction, or any other matplotlib colormap name). "
             "'galton': the ten real original color values as a fixed, non-interpolated palette "
             "(together with --galton: ten instead of five levels). "
             "'galton5': the same palette reduced to five colors, one per color family "
             "(together with --galton: five instead of ten levels).",
    )
    parser.add_argument(
        "--labels", action="store_true",
        help="Label continents and the most prominent world cities, like Galton's original",
    )
    parser.add_argument(
        "--city-scalerank", type=int, default=config.CITY_LABEL_MAX_SCALERANK, metavar="N",
        help="With --labels: label cities up to this Natural Earth SCALERANK "
             f"(0=most prominent only, higher=more cities; default {config.CITY_LABEL_MAX_SCALERANK}, "
             "~27 cities; 1: ~68; 2: ~99; 3: ~198, at 110m resolution)",
    )
    parser.add_argument(
        "--robinson", action="store_true",
        help="Robinson projection instead of the standard Mercator projection (since Galton's original)",
    )
    parser.add_argument(
        "--grid", action="store_true",
        help=f"Draw a longitude/latitude grid at {GRID_STEP_DEG}° intervals",
    )
    parser.add_argument(
        "--title", action="store_true",
        help="Show title (off by default)",
    )
    parser.add_argument(
        "--lat-limits", type=parse_lat_limits, default=None, metavar="NORTH,SOUTH",
        help="Latitude crop of the Mercator map, e.g. '80,-60' (no effect with --robinson); "
             "if not given: 80,-60 (Galton's own crop, independent of --galton)",
    )
    parser.add_argument(
        "--rivers", action="store_true",
        help="Draw major rivers (Natural Earth, 110m), at the same line width as the coastlines",
    )
    args = parser.parse_args()

    plot_h3_map(
        config.OUTPUT_H3_CSV, config.OUTPUT_CSV, config.OUTPUT_PORTS_CSV,
        config.OUTPUT_H3_MAP_PNG, config.ORIGIN_AIRPORTS,
        dpi=args.dpi, show_airports=args.airports, show_ports=args.ports, galton=args.galton,
        max_hours=args.max_hours, cmap_name=args.cmap, labels=args.labels, robinson=args.robinson,
        grid=args.grid, title=args.title, lat_limits=args.lat_limits, rivers=args.rivers,
        galton_sigma=args.galton_sigma, paper=args.paper, city_scalerank=args.city_scalerank,
    )
