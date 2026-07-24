"""Central configuration for the isochrone map computation.

Everything you'll want to tweak later (origin airports, transfer time,
rule-of-thumb constants) is collected here.
"""

import os
from pathlib import Path

# --- Paths ---
ROUTES_CSV = Path("routes.csv")
AIRPORTS_CSV = Path("airports.csv")
# London example-pipeline outputs (doc/main.py, doc/plot_map.py,
# doc/main_h3.py, plot_h3_map.py's own CLI default) live under doc/
# alongside the standalone scripts that produce/consume them - unlike
# friction_map_from_point.py's per-point outputs, which stay in the
# project root (see friction_map_from_point.py for why).
OUTPUT_CSV = Path("doc/travel_times.csv")
OUTPUT_MAP_PNG = Path("doc/travel_times_map_london_airports_points.png")

# --- Point map rendering ---
COLORMAP = "viridis_r"  # _r: dark = far away, light = close

# Resolution of the saved PNGs. Higher = sharper, but file size and
# render time scale roughly quadratically with it.
MAP_DPI = 150

# --paper: paper sizes in inches (width, height), portrait dimensions -
# the map itself keeps its own wide aspect ratio (see figsize in
# plot_h3_map.py) and is afterwards centered on a page of this format
# (landscape, since our maps are wider than tall), with blank space in
# BACKGROUND_COLOR top/bottom instead of being distorted/cropped - see
# MEMO.md. DIN sizes per ISO 216, US sizes per ANSI/ASME Y14.1.
PAPER_SIZES_IN = {
    "a0": (33.11, 46.81),
    "a1": (23.39, 33.11),
    "a2": (16.54, 23.39),
    "a3": (11.69, 16.54),
    "a4": (8.27, 11.69),
    "a5": (5.83, 8.27),
    "a6": (4.13, 5.83),
    "letter": (8.5, 11.0),
    "legal": (8.5, 14.0),
    "tabloid": (11.0, 17.0),
}

# Show airport/port points by default? Off, since otherwise even
# airports with no actual use to the flight network (e.g. without a
# single route in routes.csv, see MEMO.md) would appear unremarked as a
# point - can be shown selectively via --airports/--ports.
SHOW_AIRPORTS = False
SHOW_PORTS = False

# Total span of the color scale in hours (CLI: --max-hours) - beyond
# this the darkest shade is assigned, instead of stretching the scale
# linearly to the actual maximum (several days of sea time in the
# middle of the ocean) - like Galton's original with discrete color
# bands and a final "and beyond" category. Applies to BOTH rendering
# modes: in the plain hexagon mosaic directly as the upper end of
# Normalize() (previously incorrectly hardwired to the now-removed
# COLOR_CAP_HOURS constant, which left --max-hours without effect
# there), under --galton additionally split evenly into bands.
GALTON_MAX_HOURS = 48

# Neighbor averaging on the H3 grid itself (1 ring) smooths too weakly
# to reproduce Galton's hand-drawn, smooth bands - the band pattern
# would otherwise keep following the small-scale noise of the raw data
# (Sahara/Amazon: speckled instead of concentric rings). Instead, the
# values are interpolated onto a regular lat/lon raster and smoothed
# there with a real Gaussian filter, before `contourf` draws contiguous
# bands from it - see MEMO.md.
GALTON_GRID_DEG = 0.25       # resolution of the intermediate raster
GALTON_SIGMA_DEG = 3.0       # Gaussian smoothing radius (standard deviation)

# Copperplate-engraving retro look, only under --galton: make lines
# (coastlines, rivers, grid, frame) wobble slightly "hand-drawn"
# instead of drawing them geometrically perfect (matplotlib's built-in
# Artist.set_sketch_params(), the same mechanism behind plt.xkcd()),
# plus an aged-paper noise as a post-processing step over the finished
# PNG. Values calibrated by eye at config.MAP_DPI: enough wobble/grain
# to look engraved rather than digitally drawn, without hurting
# legibility - see MEMO.md.
# Setting randomness noticeably below matplotlib's own default (16)
# produces an almost perfect, rhythmic sine wave instead of an
# irregular jitter - the higher it is, the more "random" the waviness
# looks instead of oscillating uniformly.
# scale/length are pixels per matplotlib's docs, not points - scaled in
# _sketch() (plot_h3_map.py) with dpi/MAP_DPI, so the waviness stays
# visually the same size at a --dpi other than the one calibrated here.
RETRO_SKETCH_SCALE = 0.1       # amplitude of the line waviness, in pixels at MAP_DPI
RETRO_SKETCH_LENGTH = 15.0      # wavelength of the line waviness, in pixels at MAP_DPI
RETRO_SKETCH_RANDOMNESS = 10.0  # randomness of the waviness (dimensionless factor)
RETRO_NOISE_STRENGTH = 0.06     # strength of the paper noise overlay (0-1)

# --- Origin airports. The fastest connection across all of them is chosen. ---
ORIGIN_AIRPORTS = ["LHR", "LGW", "LCY", "STN", "LTN"]

# --- Flight-time rule of thumb: BASE_MINUTES + MINUTES_PER_BLOCK per MILES_PER_BLOCK miles ---
BASE_MINUTES = 30
MINUTES_PER_BLOCK = 60
MILES_PER_BLOCK = 500

# --- Transfer time per stopover, in hours ---
TRANSFER_HOURS = 1.5

# --- Earth radius for the Haversine formula, in miles and kilometers respectively ---
EARTH_RADIUS_MILES = 3958.8
EARTH_RADIUS_KM = 6371.0088

# --- --heli/--jetpack (friction_map_from_point.py): straight-line
# distance instead of the friction graph for the entry leg origin ->
# airport, but with limited range (unlike the unlimited flight
# network). ---
# Travel speed modeled on light/medium helicopters (Bell 429, Airbus
# H145: real-world ca. 220-260 km/h), range kept rather conservative for
# this class without refueling (Robinson R44 ~560 km, Bell 407 ~650 km).
HELI_SPEED_KMH = 220
HELI_RANGE_KM = 500

# Real fuel-powered jetpacks (Jetpack Aviation JB-10, Bell Rocket Belt)
# briefly reach ca. 100+ km/h, but only sustain that for a few minutes
# (flight duration ca. 5-10 min) - from that the range: 100 km/h * 10
# min ≈ 17 km, rounded up.
JETPACK_SPEED_KMH = 100
JETPACK_RANGE_KM = 20

# --- Count codeshare flights as their own edges in the topology? ---
INCLUDE_CODESHARE = True

# --- H3 grid: resolution and maximum search radius for candidate airports ---
H3_RESOLUTION = 4

# Now that ground time is correctly factored in (see
# nearest_airport.py), the search radius is no longer an arbitrary
# "nearness" cutoff, but purely a performance ceiling: an airport can
# only beat a closer one if its flight-time saving outweighs
# GROUND_SPEED_KMH * (distance difference). At a maximum flight-time
# span of ~34h (see travel_times.csv) and 80 km/h ground speed, no
# airport beyond a ~2700 km distance difference can still win - so a
# 3000 km search radius is effectively "no limit at all", just without
# unnecessary compute.
MAX_AIRPORT_DISTANCE_KM = 3000

# --- Assumed ground speed (car/train) between airport and tile ---
GROUND_SPEED_KMH = 80

OUTPUT_H3_CSV = Path("doc/h3_travel_times.csv")
OUTPUT_H3_MAP_PNG = Path("doc/h3_travel_times_map_london_h3_land_and_sea.png")

# --- Ports (LINERLIB, github.com/blof/LINERLIB) ---
# PORTS_CSV is the unmodified raw dataset, only relevant for
# doc/fix_ports_coordinates.py (see there). The normal pipeline reads
# PORTS_CORRECTED_CSV.
PORTS_CSV = Path("ports.csv")
PORTS_CORRECTED_CSV = Path("ports_corrected.csv")
OUTPUT_PORTS_CSV = Path("doc/ports_travel_times.csv")

# Assumed ship speed for the "last mile" port -> water tile.
SEA_SPEED_KMH = 35

# Search radius for ports around a water tile. Unlike airports, EVERY
# water tile should get a travel time, even in the middle of the
# ocean - hence practically unbounded (the maximum great-circle
# distance on Earth is about 20,015 km). That this leads to sea times
# of several days for very remote tiles is intentional and is only
# handled at rendering time (plot_h3_map.py) with a capped color scale
# - like Galton's original, which assigns the darkest shade beyond a
# threshold instead of stretching the scale linearly all the way to
# the extreme value.
MAX_PORT_DISTANCE_KM = 20_015

# --- Typography (see plot_h3_map.py: TITLE_FONT/CONTINENT_FONT/CITY_FONT) ---
# Playfair Display is a variable-font file - matplotlib can't address
# its weight axis, hence the static Bold instance (produced via
# fonttools varLib.instancer), not the variable file itself.
PLAYFAIR_BOLD_PATH = "fonts/PlayfairDisplay-Bold.ttf"
TITLE_FONT_FALLBACK_FAMILY = "serif"  # if the Playfair file is missing
# Real Baskerville isn't a free font and was previously only available
# via macOS's system installation (users on other operating systems
# would silently get a fallback font). Libre Baskerville (Impallari
# Type, SIL Open Font License, see fonts/LibreBaskerville-OFL.txt) is a
# freely usable alternative modeled on the original - static instances
# extracted from the variable-font file just like for Playfair Display
# (Bold from the Roman axis, Regular from the Italic axis).
CONTINENT_FONT_PATH = "fonts/LibreBaskerville-Bold.ttf"
CITY_FONT_PATH = "fonts/LibreBaskerville-Italic.ttf"
# Regular weight (not italic, not bold) - for the body text of the
# --galton explanation box, which unlike continent/city names needs no
# emphasis. Extracted from the same Roman axis as CONTINENT_FONT_PATH,
# just at wght=400 instead of 700.
BODY_FONT_PATH = "fonts/LibreBaskerville-Regular.ttf"
CONTINENT_FONT_FALLBACK_FAMILY = "serif"  # if the font file is missing
CITY_FONT_FALLBACK_FAMILY = "serif"
BODY_FONT_FALLBACK_FAMILY = "serif"

# For the heading of the --galton explanation box (_draw_galton_explanation):
# in the original a bold, sans-serif grotesque typeface, running wide
# rather than condensed, quite unlike the rest of the map typography
# (Playfair/Libre Baskerville, both serif). Archivo (Google Fonts, SIL
# Open Font License, see fonts/Archivo-OFL.txt) has both a width AND a
# weight axis - a static instance produced via fonttools
# varLib.instancer at maximum width (wdth=125) and maximum weight
# (wght=900), running wider as a result than the standalone (narrower)
# static "Archivo Black" cut and closer to the original than the
# too-condensed Anton tried in the meantime.
EXPLANATION_TITLE_FONT_PATH = "fonts/ArchivoExpanded-Black.ttf"
EXPLANATION_TITLE_FONT_FALLBACK_FAMILY = "sans-serif"

TITLE_FONT_SIZE = 18
CONTINENT_FONT_SIZE = 14
CITY_FONT_SIZE = 7.5
CITY_MARKER_SIZE = 2

# Natural Earth's populated_places SCALERANK (0 = most prominent world
# cities, higher = progressively less prominent) - only ranks <= this
# are labeled under --labels. Default 0 (~27 cities, at 110m resolution)
# keeps the map uncluttered; overridable via --city-scalerank since
# there's no single right answer across every DPI/paper size (e.g. 1:
# ~68 cities, 2: ~99, 3: ~198, per the cached 110m dataset).
CITY_LABEL_MAX_SCALERANK = 0

# --- Explanatory text in --galton mode (see plot_h3_map.py:_draw_galton_explanation) ---
# Like Galton's original: a brief explanatory text on the map itself
# (not part of the color legend below), with a lighter background for
# better contrast against the map underneath, stacked directly above
# the origin-star legend. Was briefly anchored (too wide for this
# position) in the Indian Ocean - narrow enough again for the original
# position on the left since the attribution wraps onto two lines.
EXPLANATION_TITLE_FONT_SIZE = 10
EXPLANATION_SUBTITLE_FONT_SIZE = 7.5
EXPLANATION_BODY_FONT_SIZE = 7
EXPLANATION_BODY_WRAP_CHARS = 34
EXPLANATION_BG_COLOR = "#e8e0cb"  # a bit darker than the first attempt (#f2ede0), but still lighter than BACKGROUND_COLOR (#dad4bb)
EXPLANATION_BG_ALPHA = 0.85
EXPLANATION_BG_PAD_PT = 5.0

# --- Signature line in --galton mode (see plot_h3_map.py:_draw_credits) ---
# Like the original, which immortalizes itself bottom-left (cartographer
# "H. Sharbau, F.G.S. del.") and bottom-right (lithographer "E. Weller.
# lith.") directly below the map frame.
CREDITS_FONT_SIZE = 7.0
CREDITS_GAP_PT = 4.0

# --- Logo bottom-right (see plot_h3_map.py:_draw_logo) ---
# On EVERY map, not just under --galton - unlike the signature line
# above, which requires the map frame that only exists in the retro look.
LOGO_SVG_PATH = "assets/ct-logo.svg"
LOGO_GAP_PT = 4.0

# --- Color legend in --galton mode (see plot_h3_map.py:_draw_galton_color_legend) ---
# Like the 1881 original: a single, brief line "Explanation of
# colours." followed by a color swatch + range per band, instead of a
# continuous color bar with its own axis - takes up noticeably less
# height as a result.
GALTON_LEGEND_FONT_SIZE = 10
GALTON_LEGEND_SWATCH_WIDTH_PT = 22
GALTON_LEGEND_SWATCH_HEIGHT_PT = 11
GALTON_LEGEND_GAP_PT = 6

# --- Web backend (see backend_server.py) ---
# Upper limit of concurrently running render jobs (ProcessPoolExecutor)
# - each job is CPU- and memory-intensive (Dijkstra + Cartopy +
# Matplotlib), hence deliberately conservative rather than based on
# core count. Overridable via the ISOSCHRONE_MAX_JOBS environment
# variable without a code change (e.g. for a more powerful host).
MAX_CONCURRENT_RENDER_JOBS = int(os.environ.get("ISOSCHRONE_MAX_JOBS", 2))
