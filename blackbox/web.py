"""Local web interface: python -m blackbox web  ->  http://127.0.0.1:8765

Standard library HTTP server bound to localhost only. Serves static files from
blackbox/static and a small JSON API over blackbox.db.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import db, importer, queries

STATIC = Path(__file__).resolve().parent / "static"
_import_lock = threading.Lock()
_import_state = {"running": False, "last": None, "error": None, "log": []}


def _filters(qs: dict) -> dict:
    return {k: qs[k][0] for k in ("type", "vehicle", "map", "since", "last") if qs.get(k) and qs[k][0]}


def make_handler(me: str, replay_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BlackBox"

        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):
            u = urlparse(self.path)
            try:
                if u.path.startswith("/api/"):
                    return self._api(u.path[5:], parse_qs(u.query))
                return self._static(u.path)
            except Exception as e:  # keep the server alive, show the error in the UI
                traceback.print_exc()
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_POST(self):
            if urlparse(self.path).path == "/api/import":
                return self._json(start_import(me, replay_dir))
            self._json({"error": "not found"}, 404)

        def _static(self, path: str):
            rel = unquote(path).lstrip("/") or "index.html"
            f = (STATIC / rel).resolve()
            if STATIC not in f.parents or not f.is_file():
                f = STATIC / "index.html"
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, f.read_bytes(), ctype)

        def _api(self, route: str, qs: dict):
            f = _filters(qs)
            con = db.connect()
            try:
                parts = route.split("/")
                if route == "filters":
                    return self._json(queries.filter_options(con, f))
                if route == "summary":
                    return self._json(queries.summary(con, f))
                if route == "battles":
                    return self._json(queries.battles(con, f))
                if parts[0] == "battle" and len(parts) == 2:
                    b = queries.battle(con, parts[1])
                    return self._json(b) if b else self._json({"error": "not found"}, 404)
                if parts[0] == "telemetry" and len(parts) == 2:
                    t = queries.telemetry(con, parts[1])
                    return self._json(t) if t else self._json({"error": "not found"}, 404)
                if route == "weapons":
                    return self._json(queries.weapons(con, f))
                if route == "skills":
                    return self._json(queries.skill_report(con, f))
                if route == "maps":
                    return self._json(queries.maps(con, f))
                if route == "vehicles":
                    return self._json(queries.vehicles(con, f))
                if route == "grind":
                    return self._json(queries.grind(con, f))
                if route == "import":
                    return self._json(_import_state)
                if route == "me":
                    return self._json({"player": me})
                return self._json({"error": "not found"}, 404)
            finally:
                con.close()

    return Handler


def start_import(me: str, replay_dir: Path) -> dict:
    if not _import_lock.acquire(blocking=False):
        return {**_import_state, "running": True}

    def job():
        _import_state.update(running=True, error=None, log=[])
        try:
            _import_state["last"] = importer.run_import(me, replay_dir, log=lambda m: _import_state["log"].append(m))
        except Exception as e:
            _import_state["error"] = f"{type(e).__name__}: {e}"
        finally:
            _import_state["running"] = False
            _import_lock.release()

    threading.Thread(target=job, daemon=True).start()
    return {**_import_state, "running": True}


def serve(me: str, replay_dir: Path, port: int = 8765, open_browser: bool = True) -> None:
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    db.connect().close()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(me, replay_dir))
    url = f"http://127.0.0.1:{port}/"
    print(f"BlackBox arayüzü: {url}   (kapatmak için Ctrl+C)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
