"""Local web interface: python -m blackbox web  ->  http://127.0.0.1:8765

Standard library HTTP server bound to localhost only. Serves static files from
blackbox/static and a small JSON API over blackbox.db.
"""

from __future__ import annotations

import json
import mimetypes
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from . import db, export, importer, queries

STATIC = Path(__file__).resolve().parent / "static"
_import_lock = threading.Lock()
_import_state = {"running": False, "last": None, "error": None, "log": [], "seq": 0, "auto": False}


def _filters(qs: dict) -> dict:
    return {k: qs[k][0] for k in ("type", "vehicle", "map", "since", "last") if qs.get(k) and qs[k][0]}


def _paths(players: list[str]) -> dict:
    return {p: db.path_for(p, i == 0) for i, p in enumerate(players)}


def make_handler(players: list[str], replay_dir: Path, browser_path: str | None = None):
    paths = _paths(players)
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
            # a custom header cannot be sent cross-site without a CORS preflight (which we never answer),
            # so other web pages cannot trigger imports or shut the app down
            if self.headers.get("X-BlackBox") != "1":
                return self._json({"error": "forbidden"}, 403)
            path = urlparse(self.path).path
            if path == "/api/import":
                return self._json(start_import(players, replay_dir))
            if path == "/api/quit":
                self._json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self._json({"error": "not found"}, 404)

        def _export(self, con, me: str, sid: str, qs: dict):
            # same guard as POST: other web pages cannot make us start a browser
            if self.headers.get("X-BlackBox") != "1":
                return self._json({"error": "forbidden"}, 403)
            fmt = (qs.get("fmt") or ["json"])[0]
            if fmt not in export.CONTENT_TYPES:
                return self._json({"error": "bilinmeyen biçim"}, 400)
            data = queries.battle(con, sid)
            if not data:
                return self._json({"error": "maç bulunamadı"}, 404)
            if fmt == "json":
                mid = data["battle"].get("match_id")
                body = export.to_json(data, queries.telemetry(con, mid) if mid else None)
            elif fmt == "csv":
                body = export.to_csv(data)
            else:
                browser = export.find_browser(browser_path)
                if not browser:
                    return self._json({"error": "PDF/PNG için Chrome ya da Edge bulunamadı."}, 501)
                theme = (qs.get("theme") or ["paper"])[0]
                theme = theme if theme in ("paper", "graphite", "olive", "arctic") else "paper"
                q = urlencode({"export": fmt, "theme": theme, "player": me})
                url = f"http://127.0.0.1:{self.server.server_address[1]}/?{q}"
                try:
                    b = data["battle"]
                    title = f"BlackBox - {b.get('map') or ''} {(b.get('started') or '')[:16].replace('T', ' ')}"
                    body = export.render(fmt, url, f"#/mac/{quote(sid)}", browser, title)
                except export.RenderError as e:
                    return self._json({"error": str(e)}, 500)
            name = export.filename(data, fmt)
            self.send_response(200)
            self.send_header("Content-Type", export.CONTENT_TYPES[fmt])
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

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
            me = (qs.get("player") or [None])[0]
            me = me if me in paths else players[0]
            con = db.connect(paths[me])
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
                if parts[0] == "export" and len(parts) == 2:
                    return self._export(con, me, parts[1], qs)
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
                if route == "trend":
                    return self._json(queries.trend(con, f))
                if route == "missing":
                    return self._json(queries.missing_results(con, f))
                if route == "import":
                    return self._json(_import_state)
                if route == "me":
                    return self._json({"player": me, "players": players})
                return self._json({"error": "not found"}, 404)
            finally:
                con.close()

    return Handler


def start_import(players: list[str], replay_dir: Path) -> dict:
    """Imports every player profile in turn (each into its own database)."""
    if not _import_lock.acquire(blocking=False):
        return {**_import_state, "running": True}

    def job():
        _import_state.update(running=True, error=None, log=[], last=None)
        try:
            log = lambda m: _import_state["log"].append(m)
            strict = len(players) > 1
            for name, path in _paths(players).items():
                if strict:
                    log(f"[{name}]")
                out = importer.run_import(name, replay_dir, log=log, db_path=path, strict=strict)
                if name == players[0] or not _import_state.get("last"):
                    _import_state["last"] = out
                else:  # sum the "new" counters over profiles
                    for k in ("telemetry", "replays", "results"):
                        _import_state["last"][k] += out[k]
        except Exception as e:
            _import_state["error"] = f"{type(e).__name__}: {e}"
        finally:
            _import_state["running"] = False
            _import_state["seq"] += 1
            _import_lock.release()

    threading.Thread(target=job, daemon=True).start()
    return {**_import_state, "running": True}


def _signature(replay_dir: Path) -> tuple:
    """Cheap fingerprint of everything an import reads: finished recordings, replays, result texts."""
    from . import session
    sig = []
    for d, pat in ((replay_dir, "*.wrpl"), (importer.RESULTS_DIR, "*.txt")):
        try:
            files = list(d.glob(pat)) if d.exists() else []
            sig.append((len(files), max((f.stat().st_mtime for f in files), default=0)))
        except OSError:
            sig.append(None)
    sig.append(len(session.list_sessions()))
    return tuple(sig)


def _auto_import(players: list[str], replay_dir: Path, interval: float = 10) -> None:
    """Imports on start and again whenever a new replay, recording or result text appears.
    Waits until the files stop changing for one interval so a replay still being written is not read."""
    last = None
    pending = None
    while True:
        try:
            sig = _signature(replay_dir)
            if sig != last:
                if pending == sig or last is None:
                    start_import(players, replay_dir)
                    last, pending = sig, None
                else:
                    pending = sig
        except Exception:
            traceback.print_exc()
        time.sleep(interval)


def _clipboard(on_saved) -> None:
    """Runs the recorder's clipboard watcher inside the web server (battle result texts)."""
    rec = Path(__file__).resolve().parent.parent / "recorder"
    sys.path.insert(0, str(rec))
    import clipboard_watch
    clipboard_watch.start_background(on_saved)


def already_running(port: int) -> bool:
    """Is a BlackBox server already answering on this port? (Windows lets two sockets bind the same port.)"""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def serve(players: list[str] | str, replay_dir: Path, port: int = 8765, open_browser: bool = True,
          auto: bool = False) -> None:
    players = [players] if isinstance(players, str) else list(players)
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    for path in _paths(players).values():
        db.connect(path).close()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(players, replay_dir))
    url = f"http://127.0.0.1:{port}/"
    print(f"BlackBox arayüzü: {url}   (kapatmak için Ctrl+C ya da arayüzde Kapat)")
    if auto:
        _import_state["auto"] = True
        if sys.platform == "win32":
            _clipboard(lambda title: print(f"[SONUÇ] kaydedildi: {title}"))
            print("Pano izleniyor: hangarda savaş sonucunu kopyaladığında otomatik kaydedilir.")
        threading.Thread(target=_auto_import, args=(players, replay_dir), name="auto-import", daemon=True).start()
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
