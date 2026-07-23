# Web Backend

`backend_server.py` wraps `friction_map_from_point.py` as a small FastAPI
app, so a map can be rendered remotely from a browser instead of the CLI.
`frontend/` is the static page it serves.

## Architecture

- **FastAPI**, serving both the `/ws/render` WebSocket route and the static
  `frontend/` files from one process/port - avoids CORS entirely, no
  separate frontend dev server needed.
- **Concurrency limit**: a module-level
  `concurrent.futures.ProcessPoolExecutor(max_workers=config.MAX_CONCURRENT_RENDER_JOBS)`.
  matplotlib/Cartopy aren't thread-safe, so each render already needs its
  own process - the same pool doubles as the required cap on simultaneous
  renders, since jobs beyond the limit simply wait in the executor's
  internal queue, no separate semaphore needed. Default `2`, overridable
  via the `ISOSCHRONE_MAX_JOBS` environment variable without a code change
  (see `config.py`).
- **Progress relay**: `friction_map_from_point.main()`'s existing
  `progress_callback` hook (see `friction_map_from_point.py`) feeds a
  `multiprocessing.Manager().Queue()`, since a worker process can't hold a
  live reference to the WebSocket directly. An asyncio task in the request
  handler drains that queue concurrently with waiting on the render job's
  `Future` and forwards each message to the client immediately.
- **No download route**: the finished PNG isn't served as a separate file.
  The handler reads it off disk once the job is done and sends it
  Base64-encoded inside the same WebSocket `"done"` message - the browser
  sets `img.src` straight to a `data:` URL, no second HTTP request. The
  file itself stays on disk afterward (same as any CLI run), so an
  identical repeat request still benefits from it as an implicit cache.
- **Reliable cancellation on disconnect**: `Future.cancel()` alone turned
  out unreliable for a job still sitting in the executor's internal queue -
  testing showed it can still race against the executor's own dispatch and
  run to completion anyway despite `cancel()` returning `True`. The actual
  mechanism is a `multiprocessing.Manager().Event()` checked inside the
  progress callback itself (see `JobCancelled` in `backend_server.py`) - a
  job aborts at its very next progress checkpoint once the server has
  noticed the client is gone, whether it had already started or not. The
  server detects the disconnect *actively*, via a second task concurrently
  awaiting `websocket.receive()`, rather than only noticing it the next
  time a message happens to be sent - a queued job that's produced no
  progress yet would otherwise go unnoticed until it started.

## Files

| File | Role |
|---|---|
| `backend_server.py` | The FastAPI app: job submission, progress relay, cancellation, static-file mount. |
| `frontend/index.html` | Form for a curated subset of `friction_map_from_point.py`'s flags (lat/lon, label, `-r`/`--resolution`, colormap, `--max-hours`, `--galton-sigma`, DPI, `--paper`, `--galton`, `--title`, `--rivers`, `--ports`, `--airports`, `--james-bond`). |
| `frontend/app.js` | Opens the WebSocket, sends the form as JSON once, renders progress bar + final image from the server's messages. |
| `frontend/style.css` | Minimal styling, light/dark aware (`color-scheme: light dark`). |

Only `friction_map_from_point.py` is wrapped so far (the most general
entry point - arbitrary `lat`/`lon`). The other CLI scripts
(`map_from_airport.py`, `plot_h3_map.py`'s own CLI, the `doc/` examples)
aren't exposed here; the same pattern (progress callback + worker function)
would extend to them if needed.

## WebSocket protocol (`/ws/render`)

- **Client → Server** (once, right after connecting): a flat JSON object -
  `lat`, `lon`, `label`, `resolution`, `galton`, `cmap`, `max_hours`,
  `galton_sigma`, `dpi`, `paper`, `title`, `rivers`, `ports`, `airports`,
  `james_bond`. Missing/empty fields fall back to
  `friction_map_from_point.main()`'s own defaults. `james_bond` maps to
  `heli=True, jetpack=True` together - `--heli`/`--jetpack` aren't
  individually selectable in the form.
- **Server → Client**, repeated: `{"type": "progress", "message": "...",
  "percent": 42}` - `percent` is a rough approximation from a fixed table
  of known milestones (`_PROGRESS_STAGES` in `backend_server.py`), not a
  real continuous measurement.
- **Server → Client**, once on success: `{"type": "done", "filename":
  "h3_travel_times_map_from_....png", "image_base64": "<PNG bytes,
  Base64>"}`.
- **Server → Client**, once on failure: `{"type": "error", "message":
  "..."}` - either a validation error (bad lat/lon/paper/dpi, caught
  before a worker is even started) or an exception from inside the render
  job itself.

## Running it

```bash
pipenv run uvicorn backend_server:app --host 127.0.0.1 --port 8000
```

Then open `http://127.0.0.1:8000/` in a browser. `--reload` is handy
during development; drop it in production. There's also a
`.claude/launch.json` entry (`backend`) for previewing it through Claude
Code's browser pane.

## Known limitations (v1 scope)

- Only a curated subset of `friction_map_from_point.py`'s flags is exposed
  in the form - no `--heli`/`--jetpack` individually (only combined via
  `--james-bond`), `--robinson`, `--grid`, `--lat-limits`, or `--labels`
  yet.
- No authentication or per-client rate limiting beyond the global
  concurrency cap - anyone who can reach the port can submit jobs.
- Rendered files (PNG/CSV) accumulate in the project root exactly as a CLI
  run would; nothing currently prunes them.
- A job that's already running (not just queued) when its client
  disconnects still runs to completion in its worker - only a still-queued
  job can be skipped early, see "Reliable cancellation on disconnect"
  above.
