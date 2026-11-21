"""War Thunder BlackBox - telemetry recorder (discovery phase).

Polls the official local telemetry API of War Thunder (http://127.0.0.1:8111)
and writes everything it gets during a match into a session folder:

    recordings/<YYYYmmdd_HHMMSS>/
        events.jsonl.gz   every poll result, one JSON object per line
        map.jpg           minimap image of the match
        meta.json         start/end time, line counts per endpoint

Only reads the HTTP API the game itself serves. No memory reading, no injection.
Standard library only (Python 3.10+).

Usage:
    python record.py            # wait for matches and record them, Ctrl+C to quit
    python record.py --probe    # fetch every endpoint once and print what comes back
"""

from __future__ import annotations

import argparse
import gzip
import json
import queue
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_URL = "http://127.0.0.1:8111"
ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = ROOT / "recordings"

# endpoint name -> (path, poll interval in seconds)
POLLED = {
    "state": ("/state", 0.1),
    "indicators": ("/indicators", 0.1),
    "map_obj": ("/map_obj.json", 0.2),
    "map_info": ("/map_info.json", 1.0),
    "mission": ("/mission.json", 1.0),
}
HUDMSG_INTERVAL = 0.5
GAMECHAT_INTERVAL = 1.0
SESSION_CHECK_INTERVAL = 1.0
END_AFTER_INVALID_SECONDS = 8.0  # match is over when map_info stays invalid this long

PROBE_PATHS = [
    "/state", "/indicators", "/map_obj.json", "/map_info.json", "/mission.json",
    "/hudmsg?lastEvt=0&lastDmg=0", "/gamechat?lastId=0", "/info", "/gunner_view",
]


def fetch_raw(path: str, timeout: float = 1.0) -> bytes | None:
    return fetch_raw_status(path, timeout)[0]


def fetch_raw_status(path: str, timeout: float = 1.0) -> tuple[bytes | None, str]:
    """Returns (body, status) where status is an HTTP code or an error name, for diagnostics."""
    try:
        with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as resp:
            return resp.read(), str(resp.status)
    except urllib.error.HTTPError as e:
        return None, str(e.code)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        return None, type(e).__name__


def fetch_json(path: str, timeout: float = 1.0):
    raw = fetch_raw(path, timeout)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {"_unparsed": raw[:2000].decode("utf-8", errors="replace")}


def max_id(items) -> int:
    ids = [it.get("id", 0) for it in items or [] if isinstance(it, dict)]
    return max(ids, default=0)


class Session:
    """One recorded match. Pollers push records into a queue, one writer thread writes them."""

    def __init__(self) -> None:
        self.started_wall = time.time()
        self.started_mono = time.monotonic()
        name = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dir = RECORDINGS_DIR / name
        self.dir.mkdir(parents=True, exist_ok=True)
        self.jsonl_path = self.dir / "events.jsonl"
        self.counts: dict[str, int] = {}
        self.queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.last_map_generation = None
        self.map_attempts = 0

    # -- writing -----------------------------------------------------------
    def put(self, ep: str, data) -> None:
        self.queue.put({
            "t": round(time.monotonic() - self.started_mono, 3),
            "wall": round(time.time(), 3),
            "ep": ep,
            "d": data,
        })

    def _writer(self) -> None:
        with open(self.jsonl_path, "w", encoding="utf-8") as f:
            while not (self.stop_event.is_set() and self.queue.empty()):
                try:
                    rec = self.queue.get(timeout=0.2)
                except queue.Empty:
                    f.flush()
                    continue
                f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")
                self.counts[rec["ep"]] = self.counts.get(rec["ep"], 0) + 1

    # -- polling -----------------------------------------------------------
    def _poll_loop(self, ep: str, path: str, interval: float) -> None:
        while not self.stop_event.is_set():
            t0 = time.monotonic()
            data = fetch_json(path, timeout=max(interval * 3, 0.5))
            if data is not None:
                self.put(ep, data)
                if ep == "map_info":
                    self._maybe_save_map(data)
            self.stop_event.wait(max(0.0, interval - (time.monotonic() - t0)))

    def _hudmsg_loop(self) -> None:
        # The game keeps old messages from earlier matches; store them once as backlog.
        backlog = fetch_json("/hudmsg?lastEvt=0&lastDmg=0") or {}
        self.put("hudmsg_backlog", backlog)
        last_evt = max_id(backlog.get("events"))
        last_dmg = max_id(backlog.get("damage"))
        while not self.stop_event.is_set():
            data = fetch_json(f"/hudmsg?lastEvt={last_evt}&lastDmg={last_dmg}")
            if isinstance(data, dict):
                evts, dmg = data.get("events") or [], data.get("damage") or []
                if evts or dmg:
                    self.put("hudmsg", data)
                    last_evt = max(last_evt, max_id(evts))
                    last_dmg = max(last_dmg, max_id(dmg))
            self.stop_event.wait(HUDMSG_INTERVAL)

    def _gamechat_loop(self) -> None:
        backlog = fetch_json("/gamechat?lastId=0") or []
        self.put("gamechat_backlog", backlog)
        last_id = max_id(backlog if isinstance(backlog, list) else [])
        while not self.stop_event.is_set():
            data = fetch_json(f"/gamechat?lastId={last_id}")
            if isinstance(data, list) and data:
                self.put("gamechat", data)
                last_id = max(last_id, max_id(data))
            self.stop_event.wait(GAMECHAT_INTERVAL)

    def _maybe_save_map(self, map_info) -> None:
        if not isinstance(map_info, dict) or not map_info.get("valid"):
            return
        gen = map_info.get("map_generation")
        if gen == self.last_map_generation or self.map_attempts >= 10:
            return
        self.map_attempts += 1
        tried = {}
        for path in (f"/map.jpg?gen={gen}", "/map.jpg"):
            raw, status = fetch_raw_status(path, timeout=5.0)
            tried[path] = f"{status} {len(raw) if raw else 0}B"
            if raw:
                self.last_map_generation = gen
                self.map_attempts = 0
                suffix = "" if gen is None else f"_{gen}"
                (self.dir / f"map{suffix}.jpg").write_bytes(raw)
                shutil.copyfile(self.dir / f"map{suffix}.jpg", self.dir / "map.jpg")
                break
        self.put("map_fetch", {"map_generation": gen, "attempt": self.map_attempts, "tried": tried})

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        targets = [threading.Thread(target=self._writer, name="writer")]
        for ep, (path, interval) in POLLED.items():
            targets.append(threading.Thread(target=self._poll_loop, args=(ep, path, interval), name=ep))
        targets.append(threading.Thread(target=self._hudmsg_loop, name="hudmsg"))
        targets.append(threading.Thread(target=self._gamechat_loop, name="gamechat"))
        for th in targets:
            th.daemon = True
            th.start()
        self.threads = targets

    def stop(self) -> None:
        self.stop_event.set()
        for th in self.threads:
            th.join(timeout=5)
        # compress the raw log
        gz_path = self.jsonl_path.with_suffix(".jsonl.gz")
        with open(self.jsonl_path, "rb") as src, gzip.open(gz_path, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        self.jsonl_path.unlink()
        meta = {
            "started": datetime.fromtimestamp(self.started_wall).isoformat(timespec="seconds"),
            "ended": datetime.now().isoformat(timespec="seconds"),
            "duration_s": round(time.monotonic() - self.started_mono, 1),
            "counts": self.counts,
            "recorder_version": 1,
        }
        (self.dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def in_match() -> bool | None:
    """True/False from map_info.valid, None when the game API is not reachable."""
    info = fetch_json("/map_info.json")
    if info is None:
        return None
    return bool(isinstance(info, dict) and info.get("valid"))


STOP = threading.Event()


def _stop_on_eof() -> None:
    """Started by BlackBox (hidden window): the parent closes our stdin to ask for a clean stop."""
    def wait():
        try:
            while sys.stdin.buffer.read(1024):
                pass
        except (OSError, ValueError, AttributeError):
            pass
        STOP.set()
    threading.Thread(target=wait, name="stdin-eof", daemon=True).start()


def run(clipboard: bool = True) -> None:
    print(f"BlackBox recorder - recordings go to {RECORDINGS_DIR}")
    if clipboard and sys.platform == "win32":
        import clipboard_watch
        clipboard_watch.start_background(lambda title: print(f"\n[SONUÇ] kaydedildi: {title}"))
        print("Clipboard watcher on: copy battle results in the hangar and they are saved automatically.")
    print("Waiting for War Thunder (Ctrl+C to quit)...")
    session: Session | None = None
    invalid_since: float | None = None
    last_status = ""
    last_print = 0.0
    try:
        while True:
            if STOP.is_set():
                raise KeyboardInterrupt
            state = in_match()
            now = time.monotonic()
            if state and session is None:
                session = Session()
                session.start()
                invalid_since = None
                print(f"\n[REC] Match detected -> {session.dir.name}")
            elif session is not None:
                if state:
                    invalid_since = None
                else:
                    invalid_since = invalid_since or now
                    if now - invalid_since >= END_AFTER_INVALID_SECONDS:
                        session.stop()
                        print(f"\n[OK ] Match over, saved {session.dir.name} "
                              f"({sum(session.counts.values())} records)")
                        session = None

            status = ("game not running" if state is None and session is None
                      else "in hangar" if session is None
                      else f"recording {now - session.started_mono:6.0f}s  "
                           f"records={sum(session.counts.values())}")
            if status != last_status or now - last_print > 5:
                print(f"\r{status:<60}", end="", flush=True)
                last_status, last_print = status, now
            time.sleep(SESSION_CHECK_INTERVAL)
    except KeyboardInterrupt:
        print()
        if session is not None:
            print("Stopping, saving current session...")
            session.stop()
            print(f"[OK ] Saved {session.dir.name}")


def probe() -> None:
    out_dir = RECORDINGS_DIR / "_probe"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = {}
    for path in PROBE_PATHS:
        raw = fetch_raw(path)
        if raw is None:
            print(f"{path:<32} -> no response")
            results[path] = None
            continue
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            print(f"{path:<32} -> {len(raw)} bytes, not JSON")
            results[path] = raw[:500].decode("utf-8", errors="replace")
            continue
        results[path] = data
        if isinstance(data, dict):
            print(f"{path:<32} -> dict, {len(data)} keys: {' | '.join(list(data)[:12])}"
                  + (" ..." if len(data) > 12 else ""))
        elif isinstance(data, list):
            print(f"{path:<32} -> list of {len(data)}")
        else:
            print(f"{path:<32} -> {type(data).__name__}")
    out = out_dir / f"probe_{stamp}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nFull output saved to {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--probe", action="store_true", help="fetch every endpoint once and exit")
    parser.add_argument("--url", default=BASE_URL, help="API base URL (default %(default)s)")
    parser.add_argument("--no-clipboard", action="store_true", help="do not watch the clipboard for battle results")
    parser.add_argument("--stop-on-eof", action="store_true", help="stop cleanly when stdin closes (used by BlackBox)")
    args = parser.parse_args()
    if args.stop_on_eof:
        _stop_on_eof()
    BASE_URL = args.url.rstrip("/")
    if sys.platform == "win32" and sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    probe() if args.probe else run(clipboard=not args.no_clipboard)
