"""FastAPI-Backend für Fernzugriff auf friction_map_from_point.py per WebSocket.

Rendert Karten in eigenen Worker-Prozessen (ProcessPoolExecutor, Obergrenze
siehe config.MAX_CONCURRENT_RENDER_JOBS) statt im Server-Prozess selbst -
matplotlib und Cartopy sind nicht thread-sicher, und dieselbe Prozess-
Obergrenze ist zugleich die geforderte Begrenzung gleichzeitiger Renders:
weitere Jobs über die Obergrenze hinaus warten automatisch in der internen
Warteschlange des Executors, ganz ohne zusätzliche Semaphore.

Fortschritt wird über eine multiprocessing.Manager().Queue() vom Worker- in
den Server-Prozess zurückgereicht (ein direkter Python-Callback kann nicht
über die Prozessgrenze übergeben werden) und per WebSocket an den Client
weitergeleitet. Das fertige PNG wird nicht als eigene Datei ausgeliefert,
sondern direkt Base64-codiert in der Abschluss-Nachricht mitgeschickt - kein
zweiter Request nötig.

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

# Ein Manager-Prozess und ein Worker-Pool fürs ganze Server-Leben, nicht pro
# Request neu gestartet - Manager() startet einen eigenen Server-Prozess für
# die Queue-Proxys, das pro Anfrage neu zu tun wäre unnötiger Overhead.
_MANAGER = multiprocessing.Manager()
_EXECUTOR = ProcessPoolExecutor(max_workers=config.MAX_CONCURRENT_RENDER_JOBS)

# Meilensteine aus friction_map_from_point.main() (siehe dort, die
# _report()-Aufrufe) grob gewichtet für eine Fortschritts-Prozentanzeige -
# keine echte kontinuierliche Messung, nur eine plausible Annäherung anhand
# bekannter, immer in derselben Reihenfolge auftretender Etappen. Reihenfolge
# hier ist unerheblich, jede eingehende Meldung wird gegen alle Muster
# geprüft und übernimmt bei Treffer den zugehörigen Wert.
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


def _run_render_job(params, progress_queue):
    """Läuft in einem eigenen Worker-Prozess (ProcessPoolExecutor) - der
    Import von friction_map_from_point passiert bewusst erst hier drin,
    nicht auf Modulebene, damit er (und die darin geladenen schweren
    Abhängigkeiten) im Worker- statt im Server-Prozess stattfindet.
    progress_queue.put direkt als Callback übergeben, main() ruft es mit
    genau einer Zeichenkette pro Meilenstein auf (siehe _report() dort)."""
    import friction_map_from_point

    return friction_map_from_point.main(
        progress_callback=progress_queue.put, verbose=False, **params,
    )


def _build_job_params(payload):
    """Validiert/normalisiert die vom Client gesendeten Request-Parameter zu
    main()-kwargs - wirft ValueError bei ungültigen Werten (z.B. --paper),
    das der Aufrufer in eine Fehlermeldung an den Client übersetzt, statt den
    Worker-Prozess erst mit einer kaputten Eingabe zu starten."""
    lat = float(payload["lat"])
    lon = float(payload["lon"])
    if not (-90 <= lat <= 90):
        raise ValueError(f"Breitengrad {lat} liegt außerhalb von -90..90.")
    if not (-180 <= lon <= 180):
        raise ValueError(f"Längengrad {lon} liegt außerhalb von -180..180.")

    paper = payload.get("paper") or None
    if paper:
        paper = parse_paper(paper)  # wirft ValueError bei ungültigem Format

    dpi = int(payload.get("dpi") or config.MAP_DPI)
    if not (36 <= dpi <= 300):
        # Nach oben begrenzt, damit ein Request nicht versehentlich (oder
        # absichtlich) einen einzelnen Worker-Slot minutenlang blockiert.
        raise ValueError("dpi muss zwischen 36 und 300 liegen.")

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


app = FastAPI()


@app.websocket("/ws/render")
async def render_socket(websocket: WebSocket):
    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        params = _build_job_params(payload)
    except (KeyError, TypeError, ValueError) as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    progress_queue = _MANAGER.Queue()
    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(_EXECUTOR, _run_render_job, params, progress_queue)

    percent = 0
    try:
        # Bewusst queue.get_nowait() + asyncio.sleep() statt eines
        # blockierenden queue.get(timeout=...) - letzteres würde den
        # gesamten Event-Loop für die Dauer des Timeouts einfrieren und
        # damit ALLE anderen gleichzeitigen WebSocket-Verbindungen blockieren,
        # nicht nur diese eine.
        while not future.done():
            try:
                message = progress_queue.get_nowait()
            except Empty:
                await asyncio.sleep(0.15)
                continue
            percent = _progress_percent(message, percent)
            await websocket.send_json({"type": "progress", "message": message, "percent": percent})

        # Nach Jobende ggf. noch verbliebene, noch nicht abgeholte Meldungen
        # nachreichen (z.B. die letzte "Drawing map ..."-Meldung, falls sie
        # erst kurz vor future.done() in der Queue landete).
        while True:
            try:
                message = progress_queue.get_nowait()
            except Empty:
                break
            percent = _progress_percent(message, percent)
            await websocket.send_json({"type": "progress", "message": message, "percent": percent})

        png_path = future.result()  # wirft eine im Worker aufgetretene Exception hier erneut
    except WebSocketDisconnect:
        return
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    image_bytes = Path(png_path).read_bytes()
    await websocket.send_json({
        "type": "done",
        "filename": png_path,
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
    })
    await websocket.close()


# Zuletzt registriert, damit die explizite WebSocket-Route oben Vorrang hat -
# Starlette prüft Routen in Registrierungsreihenfolge, der StaticFiles-Mount
# an "/" dient als Auffangregel für alles, was keine eigene Route hat.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
