"""Match analysis export: JSON, CSV, PDF and PNG.

JSON and CSV are built here from the same data the match page shows. PNG is rendered by a local
Chrome or Edge in headless mode from the match page's export view (no extra libraries): the page is
loaded once to measure its height, then screenshotted at exactly that size. PDF wraps that PNG.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from . import __version__

WIDTH = 1280            # CSS px; the match page lays out in two columns at this width
SCALE = 2               # PNG pixel density (sharp on phones)
_render_lock = threading.Lock()

CONTENT_TYPES = {
    "json": "application/json; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "pdf": "application/pdf",
    "png": "image/png",
}


# ---------------------------------------------------------------- file name
def _slug(s: str) -> str:
    s = (s or "").translate(str.maketrans("ıİşŞğĞüÜöÖçÇ", "iIsSgGuUoOcC"))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-") or "mac"


def filename(data: dict, fmt: str) -> str:
    b = data["battle"]
    when = (b.get("started") or "")[:16].replace("T", "_").replace(":", "").replace("-", "")
    return f"BlackBox_{_slug(b.get('map'))}_{when or 'tarihsiz'}.{fmt}"


# ---------------------------------------------------------------- JSON
def to_json(data: dict, telemetry: dict | None = None) -> bytes:
    out = {
        "format": "blackbox-match",
        "version": 1,
        "app_version": __version__,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **data,
    }
    if telemetry:
        # time series: [t s, altitude m, true airspeed km/h, Mach, G]; track: [t s, x, y] map-normalized
        out["telemetry"] = {
            "series_columns": ["t_s", "alt_m", "tas_kmh", "mach", "g"],
            "series": telemetry.get("series", []),
            "track_columns": ["t_s", "x", "y"],
            "track": telemetry.get("track", []),
            "events": telemetry.get("events", []),
        }
    return json.dumps(out, ensure_ascii=False, indent=2, default=str).encode("utf-8")


# ---------------------------------------------------------------- CSV
def _mmss(s) -> str:
    if s is None:
        return ""
    s = int(s)
    return f"{s // 60}:{s % 60:02d}"


RESULT_TR = {"win": "Zafer", "loss": "Yenilgi"}


def to_csv(data: dict) -> bytes:
    """One file, several tables separated by blank lines. ';' and a BOM so Excel (Turkish locale) opens it
    straight into columns."""
    b, players = data["battle"], data["players"]
    me = next((p for p in players if p.get("is_me")), None)
    my_team = me["team"] if me else None
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")

    w.writerow(["BlackBox maç analizi"])
    end = b.get("end_s")
    for k, v in [
        ("Harita", b.get("map")), ("Mod", b.get("mode") or b.get("battle_class")), ("Tarih", (b.get("started") or "")[:16].replace("T", " ")),
        ("Araç", b.get("vehicle_name") or b.get("vehicle")), ("Sonuç", RESULT_TR.get(b.get("result"), "Bilinmiyor")),
        ("Süre", _mmss(end)), ("Oturum", b.get("session_id")),
        ("Kill", b.get("kills")), ("Ölüm", b.get("deaths")), ("Asist", b.get("assists")), ("Skor", b.get("score")),
        ("Lobi sırası", f"{b.get('lobby_pos')}/{b.get('n_players')}" if b.get("lobby_pos") else ""),
        ("Takım sırası", b.get("team_pos")), ("Üs", b.get("bases_est")), ("Füzeden kaçış", b.get("missile_evades")),
        ("Net SL", b.get("total_sl")), ("RP", b.get("total_rp")),
    ]:
        w.writerow([k, "" if v is None else v])

    w.writerow([])
    w.writerow(["Seninle ilgili olaylar"])
    w.writerow(["Zaman", "Olay", "Oyuncu", "Araç", "Silah"])
    for k in data["kills"]:
        t = _mmss(k["ms"] / 1000)
        if k.get("me_killer") and k.get("destroyed_weapon"):
            w.writerow([t, "Füze vuruldu", "", k.get("destroyed_name"), k.get("weapon_name")])
        elif k.get("me_killer"):
            w.writerow([t, "Kill", k.get("victim_name") or "AI hedef", k.get("victim_vehicle_name"), k.get("weapon_name")])
        elif k.get("me_victim"):
            w.writerow([t, "Ölüm", k.get("killer_name") or "kaza", k.get("killer_vehicle_name"), k.get("weapon_name")])

    res = data.get("result")
    if res:
        w.writerow([])
        w.writerow(["Ödüller"])
        w.writerow(["Kalem", "Adet", "SL", "RP"])
        for name, v in (res.get("categories") or {}).items():
            w.writerow([name, v.get("count") or "", v.get("sl") if v.get("sl") is not None else "",
                        v.get("rp") if v.get("rp") is not None else ""])
        w.writerow(["Otomatik tamir", "", res.get("repair_sl"), ""])
        w.writerow(["Toplam (net)", "", res.get("total_sl"), res.get("total_rp")])

    teams = [t for t in (my_team, 2 if my_team == 1 else 1) if t is not None] or sorted({p["team"] for p in players})
    for team in teams:
        w.writerow([])
        w.writerow(["Senin takımın" if team == my_team else "Rakip takım"])
        w.writerow(["Oyuncu", "Klan", "Araç", "K", "Ö", "A", "Skor", "Füzeden kaçış", "Sen"])
        for p in (p for p in players if p["team"] == team):
            w.writerow([p.get("name"), p.get("clan") or "", p.get("vehicle_name") or p.get("vehicle"), p.get("kills"),
                        p.get("deaths"), p.get("assists"), p.get("score"), p.get("missile_evades"),
                        "evet" if p.get("is_me") else ""])

    w.writerow([])
    w.writerow(["Tüm kill'ler"])
    w.writerow(["Zaman", "Vuran", "Vuranın aracı", "Vurulan", "Vurulanın aracı", "Silah", "Vuranın takımı"])
    team_of = {p["idx"]: p["team"] for p in players}
    for k in data["kills"]:
        team = team_of.get(k.get("killer_idx"))
        side = "" if team is None else ("senin" if team == my_team else "rakip")
        victim = k.get("destroyed_name") and f"{k['destroyed_name']} (füze)" or k.get("victim_name") or "AI hedef"
        w.writerow([_mmss(k["ms"] / 1000), k.get("killer_name") or "kaza", k.get("killer_vehicle_name"), victim,
                    "" if k.get("destroyed_weapon") else k.get("victim_vehicle_name"), k.get("weapon_name"), side])
    return ("﻿" + buf.getvalue()).encode("utf-8")


# ---------------------------------------------------------------- PDF / PNG via headless Chrome or Edge
def find_browser(configured: str | None = None) -> str | None:
    cands = [configured] if configured else []
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if base:
                cands += [Path(base) / "Google/Chrome/Application/chrome.exe",
                          Path(base) / "Microsoft/Edge/Application/msedge.exe"]
    for name in ("chrome", "google-chrome", "chromium", "chromium-browser", "msedge", "microsoft-edge"):
        cands.append(shutil.which(name))
    for c in cands:
        if c and Path(c).is_file():
            return str(c)
    return None


class RenderError(RuntimeError):
    pass


def _run(browser: str, args: list[str], profile: str, timeout: float = 60) -> subprocess.CompletedProcess:
    cmd = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
           "--disable-extensions", "--hide-scrollbars", "--mute-audio", f"--user-data-dir={profile}", *args]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired as e:
        raise RenderError("Tarayıcı zamanında yanıt vermedi.") from e


def render(fmt: str, url: str, fragment: str, browser: str, title: str = "BlackBox") -> bytes:
    """fmt 'pdf' or 'png'. url + fragment: the match page's export view on this server (url has a query).

    The PDF is the PNG on one page: Chrome's print layout reflows the page (other breakpoints, panels split
    across pages), while the screenshot looks exactly like the match page."""
    with _render_lock, tempfile.TemporaryDirectory(prefix="blackbox-export-") as tmp:
        profile = str(Path(tmp) / "profile")     # own profile: works while the user's browser is open
        # pass 1: let the page load its data and report its full height
        r = _run(browser, [f"--window-size={WIDTH},1000", "--virtual-time-budget=15000", "--dump-dom", url + fragment], profile)
        dom = r.stdout.decode("utf-8", "replace")
        m = re.search(r'data-export-h="(\d+)"', dom)
        if not m:
            err = re.search(r'data-export-error="([^"]*)"', dom)
            raise RenderError(err.group(1) if err else "Sayfa dışa aktarma için hazırlanamadı.")
        h = int(m.group(1)) + 2
        out = Path(tmp) / "out.png"
        _run(browser, [f"--window-size={WIDTH},{h}", f"--force-device-scale-factor={SCALE}", f"--screenshot={out}",
                       "--virtual-time-budget=15000", url + fragment], profile)
        if not out.is_file() or out.stat().st_size == 0:
            raise RenderError("Tarayıcı çıktı üretmedi.")
        png = out.read_bytes()
        return png if fmt == "png" else png_to_pdf(png, title)


# ---------------------------------------------------------------- PDF from PNG (no libraries)
def _png_parts(png: bytes) -> tuple[int, int, int, bytes]:
    """(width, height, PDF colors, zlib image data) of an 8-bit, non-interlaced RGB or grey PNG."""
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise RenderError("Geçersiz PNG.")
    pos, idat, w = 8, [], None
    while pos < len(png):
        n, kind = struct.unpack(">I4s", png[pos:pos + 8])
        body = png[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth != 8 or ctype not in (0, 2) or interlace:
                raise RenderError("PNG biçimi PDF için desteklenmiyor.")
            colors = 3 if ctype == 2 else 1
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
        pos += 12 + n
    if w is None or not idat:
        raise RenderError("Geçersiz PNG.")
    return w, h, colors, b"".join(idat)


def png_to_pdf(png: bytes, title: str = "BlackBox") -> bytes:
    """One page as wide as A4, as tall as the image needs. PNG rows keep their filters: PDF's
    FlateDecode with /Predictor 15 reads them as they are, so nothing is decoded here."""
    w, h, colors, data = _png_parts(png)
    pw = 595.28                                    # A4 width in points
    ph = round(pw * h / w, 2)
    safe = title.encode("ascii", "replace").decode().replace("\\", "").replace("(", "[").replace(")", "]")
    content = f"q {pw} 0 0 {ph} 0 0 cm /Im0 Do Q".encode()
    space = "DeviceRGB" if colors == 3 else "DeviceGray"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pw} {ph}] /Resources << /XObject << /Im0 4 0 R >> >> "
        f"/Contents 5 0 R >>".encode(),
        f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /{space} /BitsPerComponent 8 "
        f"/Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors {colors} /BitsPerComponent 8 /Columns {w} >> "
        f"/Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream",
        f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream",
        f"<< /Title ({safe}) /Producer (War Thunder BlackBox {__version__}) >>".encode(),
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {len(objs)} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
