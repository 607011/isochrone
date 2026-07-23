"""FastAPI backend for remote access to friction_map_from_point.py via WebSocket.

Renders maps in dedicated worker processes (ProcessPoolExecutor, limit
see config.MAX_CONCURRENT_RENDER_JOBS) instead of in the server process
itself - matplotlib and Cartopy aren't thread-safe, and this same
process limit doubles as the required cap on concurrent renders:
further jobs beyond the limit wait automatically in the executor's
internal queue, with no extra semaphore needed.

Progress is passed back from the worker to the server process via a
multiprocessing.Manager().Queue() (a direct Python callback can't be
passed across the process boundary) and forwarded to the client over
WebSocket. The finished PNG isn't served as a separate file, but sent
directly base64-encoded in the completion message - no second request
needed.

Start: pipenv run uvicorn backend_server:app --reload
"""

import asyncio
import base64
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from queue import Empty

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import config
from plot_h3_map import parse_paper

# One manager process and one worker pool for the server's whole
# lifetime, not restarted per request - Manager() starts its own
# server process for the queue proxies, doing that again per request
# would be unnecessary overhead.
_MANAGER = multiprocessing.Manager()
_EXECUTOR = ProcessPoolExecutor(max_workers=config.MAX_CONCURRENT_RENDER_JOBS)

# Milestones from friction_map_from_point.main() (see there, the
# _report() calls) roughly weighted for a progress-percentage display -
# not a real continuous measurement, just a plausible approximation
# based on known stages that always occur in the same order. Order
# here doesn't matter, every incoming message is checked against all
# patterns and takes on the matching value on a hit.
_PROGRESS_STAGES = [
    (lambda m: m.startswith("Loading airport data"), 5),
    (lambda m: m.startswith("Loading friction-graph"), 15),
    (lambda m: m.startswith("Calculating combined"), 25),
    (lambda m: m.endswith("airports reachable."), 30),
    (lambda m: m.startswith("Distributing ground time"), 55),
    (lambda m: m.startswith("Building port tiles"), 65),
    (lambda m: m.startswith("Applying fly-then-walk"), 75),
    (lambda m: m.startswith("Coloring tiles within"), 78),
    (lambda m: m.startswith("Writing "), 85),
    (lambda m: m.startswith("Drawing map"), 92),
]


def _progress_percent(message, last_percent):
    for matches, percent in _PROGRESS_STAGES:
        if matches(message):
            return percent
    return last_percent


class JobCancelled(Exception):
    """Raised inside the worker process, from within the progress
    callback, once the server has noticed the client is gone -
    interrupts main() at its next _report() checkpoint (see
    friction_map_from_point.py) instead of letting it render to
    completion for nobody. Deliberately a plain Exception, not
    asyncio.CancelledError: it crosses the process boundary through the
    Future's normal exception-pickling path, not asyncio's cancellation
    machinery, and ProcessPoolExecutor.Future.cancel() alone is not
    reliable here - whether a queued job actually gets skipped depends
    on a race against the executor's internal dispatch queue, confirmed
    by testing to sometimes let an already "cancelled" job run to
    completion anyway."""


def _run_render_job(params, progress_queue, cancel_event):
    """Runs in its own worker process (ProcessPoolExecutor) - the import
    of friction_map_from_point deliberately happens only in here, not
    at module level, so that it (and the heavy dependencies it loads)
    happens in the worker process rather than the server process. Pool
    workers are reused across jobs, so this import only pays its cost
    on that worker's first job; later jobs in the same worker hit
    Python's module cache."""
    import friction_map_from_point

    def progress_callback(msg):
        # Checked first, before the message is even queued - once the
        # client is gone nobody reads progress_queue anyway, and this
        # is the checkpoint that lets an already-dispatched job bail
        # out early instead of running to completion unwatched.
        if cancel_event.is_set():
            raise JobCancelled(msg)
        progress_queue.put(msg)

    return friction_map_from_point.main(
        progress_callback=progress_callback, verbose=False, **params,
    )


def _build_job_params(payload):
    """Validates/normalizes the request parameters sent by the client
    into main() kwargs - raises ValueError for invalid values (e.g.
    --paper), which the caller translates into an error message to the
    client, instead of starting the worker process with broken input
    in the first place."""
    lat = float(payload["lat"])
    lon = float(payload["lon"])
    if not (-90 <= lat <= 90):
        raise ValueError(f"Latitude {lat} is outside -90..90.")
    if not (-180 <= lon <= 180):
        raise ValueError(f"Longitude {lon} is outside -180..180.")

    paper = payload.get("paper") or None
    if paper:
        paper = parse_paper(paper)  # raises ValueError for an invalid format

    dpi = int(payload.get("dpi") or config.MAP_DPI)
    if not (36 <= dpi <= 300):
        # Capped from above so a request can't accidentally (or
        # deliberately) block a single worker slot for minutes.
        raise ValueError("dpi must be between 36 and 300.")

    return {
        "lat": lat,
        "lon": lon,
        "label": payload.get("label") or None,
        "galton": bool(payload.get("galton")),
        "cmap_name": payload.get("cmap") or None,
        "max_hours": float(payload.get("max_hours") or config.GALTON_MAX_HOURS),
        "dpi": dpi,
        "paper": paper,
        "title": bool(payload.get("title")),
    }


def _abandon_job(future, cancel_event):
    """Called once a client is confirmed gone. cancel_event.set() is the
    reliable path (checked inside the worker's progress callback, see
    _run_render_job) - future.cancel() is kept alongside it since it's
    free and occasionally wins outright for a job that hasn't been
    dispatched to a worker at all yet. The done-callback below just
    retrieves the eventual JobCancelled/CancelledError so asyncio
    doesn't log it as "exception was never retrieved" - nobody's left
    to hand the result to."""
    cancel_event.set()
    future.cancel()

    def _retrieve(f):
        try:
            f.exception()
        except asyncio.CancelledError:
            pass

    future.add_done_callback(_retrieve)


app = FastAPI()


@app.websocket("/ws/render")
async def render_socket(websocket: WebSocket):
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        params = _build_job_params(payload)
    except WebSocketDisconnect:
        return
    except (KeyError, TypeError, ValueError) as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    progress_queue = _MANAGER.Queue()
    cancel_event = _MANAGER.Event()
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_EXECUTOR, _run_render_job, params, progress_queue, cancel_event)

    # Detecting a disconnect passively (only when send_json happens to
    # fail) doesn't help a job still waiting in the executor's queue -
    # such a job produces no progress messages, so send_json is never
    # attempted, and the disconnect goes unnoticed until the job has
    # already started (at which point cancel() is a no-op). Actively
    # watching receive() catches it the moment the client leaves,
    # whether the job has started or not.
    disconnected = asyncio.Event()

    async def watch_disconnect():
        try:
            while True:
                await websocket.receive()
        except WebSocketDisconnect:
            disconnected.set()

    watcher_task = asyncio.ensure_future(watch_disconnect())

    percent = 0
    try:
        # Deliberately queue.get_nowait() + a timed wait on the
        # disconnect event instead of a blocking queue.get(timeout=...)
        # - the latter would freeze the entire event loop for the
        # duration of the timeout, blocking ALL other concurrent
        # WebSocket connections, not just this one.
        while not future.done() and not disconnected.is_set():
            try:
                message = progress_queue.get_nowait()
            except Empty:
                try:
                    await asyncio.wait_for(disconnected.wait(), timeout=0.15)
                except asyncio.TimeoutError:
                    pass
                continue
            percent = _progress_percent(message, percent)
            await websocket.send_json({"type": "progress", "message": message, "percent": percent})

        if disconnected.is_set():
            _abandon_job(future, cancel_event)
            return

        # After the job ends, flush any remaining messages not yet
        # picked up (e.g. the last "Drawing map ..." message, if it
        # only landed in the queue shortly before future.done()).
        while True:
            try:
                message = progress_queue.get_nowait()
            except Empty:
                break
            percent = _progress_percent(message, percent)
            await websocket.send_json({"type": "progress", "message": message, "percent": percent})

        png_path = future.result()  # re-raises an exception that occurred in the worker
    except WebSocketDisconnect:
        _abandon_job(future, cancel_event)
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return
    finally:
        watcher_task.cancel()

    image_bytes = Path(png_path).read_bytes()
    await websocket.send_json({
        "type": "done",
        "filename": png_path,
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
    })
    await websocket.close()


# Registered last, so the explicit WebSocket route above takes
# precedence - Starlette checks routes in registration order, the
# StaticFiles mount at "/" serves as the catch-all for anything without
# its own route.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
