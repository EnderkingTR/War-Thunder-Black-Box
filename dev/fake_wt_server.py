"""Fake War Thunder 8111 API for testing the recorder without the game.

Simulates: hangar for 3 s, a match of --match seconds, then hangar again.
Field names mimic the real API but values are invented.

    python dev/fake_wt_server.py --port 8112 --match 15
    python recorder/record.py --url http://127.0.0.1:8112
"""

import argparse
import json
import math
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

T0 = time.monotonic()
MATCH_START, MATCH_LEN = 3.0, 15.0
DAMAGE = [
    (5.0, "PlayerA (F-16A) shot down EnemyB (MiG-23ML)"),
    (9.0, "EnemyC (Su-22M3) destroyed PlayerD (F-5E)"),
    (12.0, "PlayerA (F-16A) has achieved \"Head-on\""),
]


def match_time():
    t = time.monotonic() - T0 - MATCH_START
    return t if 0 <= t < MATCH_LEN else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        mt = match_time()
        live = mt is not None
        if u.path == "/map_info.json":
            self.send({"valid": live, "map_generation": 1 if live else 0,
                       "grid_steps": [8192, 8192], "map_min": [0, 0], "map_max": [65536, 65536]})
        elif u.path == "/state":
            if not live:
                return self.send({"valid": False})
            self.send({"valid": True, "H, m": 3000 + 500 * math.sin(mt), "TAS, km/h": 900 + 50 * math.cos(mt),
                       "IAS, km/h": 700, "M": 0.85, "AoA, deg": 4.2, "Ny": 1.0 + abs(math.sin(mt)) * 5,
                       "throttle 1, %": 100, "Mfuel, kg": 2000 - mt})
        elif u.path == "/indicators":
            self.send({"valid": live, "type": "f_16a" if live else "dummy_plane", "altitude_hour": 3000,
                       "compass": (mt or 0) * 10 % 360})
        elif u.path == "/map_obj.json":
            if not live:
                return self.send([])
            self.send([
                {"type": "aircraft", "color": "#fafa1a", "icon": "Player", "x": 0.5 + 0.01 * mt, "y": 0.5,
                 "dx": 1, "dy": 0},
                {"type": "aircraft", "color": "#f40C00", "icon": "Fighter", "x": 0.3, "y": 0.6 - 0.01 * mt,
                 "dx": 0, "dy": -1},
                {"type": "airfield", "color": "#174DFF", "sx": 0.1, "sy": 0.1, "ex": 0.12, "ey": 0.15},
            ])
        elif u.path == "/mission.json":
            self.send({"status": "running" if live else "fail", "objectives": [
                {"primary": True, "status": "in_progress", "text": "Destroy the enemy"}]})
        elif u.path == "/hudmsg":
            last = int(q.get("lastDmg", ["0"])[0])
            dmg = [{"id": i + 1, "msg": m, "sender": "", "enemy": False, "mode": "", "time": int(t)}
                   for i, (t, m) in enumerate(DAMAGE) if live and mt >= t]
            self.send({"events": [], "damage": [d for d in dmg if d["id"] > last]})
        elif u.path == "/gamechat":
            last = int(q.get("lastId", ["0"])[0])
            msgs = [{"id": 1, "msg": "gl hf", "sender": "PlayerA", "enemy": False, "mode": "All", "time": 2}]
            self.send([m for m in msgs if live and mt > 2 and m["id"] > last])
        elif u.path == "/map.jpg":
            self.send(b"\xff\xd8\xff\xe0fakejpeg\xff\xd9", "image/jpeg")
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8112)
    ap.add_argument("--match", type=float, default=15.0)
    a = ap.parse_args()
    MATCH_LEN = a.match
    print(f"fake WT API on http://127.0.0.1:{a.port} (match {MATCH_LEN}s after {MATCH_START}s)")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
