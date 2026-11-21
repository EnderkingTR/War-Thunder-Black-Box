"""Watches the Windows clipboard for copied War Thunder battle result texts.

When you press "copy" on a battle result notification in the hangar, the text is
saved to results/<session_id>.txt (one file per battle). Only reads your own
clipboard via the Win32 API; standard library only.

Standalone:  python recorder/clipboard_watch.py
"""

from __future__ import annotations

import ctypes
import re
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"

HEADER_RE = re.compile(r"^\[[^\]]+\]\s+.+?\s+görevinde\s+(?:zafer|yenilgi)!\s*$", re.M)
SESSION_RE = re.compile(r"^Oturum:\s*([0-9a-f]{6,})\s*$", re.M)
CF_UNICODETEXT = 13

if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.CloseClipboard.restype = wintypes.BOOL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]


def read_clipboard_text() -> str | None:
    if sys.platform != "win32":
        return None
    for _ in range(5):  # another app may hold the clipboard for a moment
        if _user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return None
    try:
        h = _user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = _kernel32.GlobalLock(h)
        if not p:
            return None
        try:
            return ctypes.wstring_at(p)
        finally:
            _kernel32.GlobalUnlock(h)
    finally:
        _user32.CloseClipboard()


def save_results(text: str) -> list[str]:
    """Splits a copied text into battles and saves new ones. Returns saved descriptions."""
    text = text.replace("\r\n", "\n")
    starts = [m.start() for m in HEADER_RE.finditer(text)]
    saved = []
    RESULTS_DIR.mkdir(exist_ok=True)
    for a, b in zip(starts, starts[1:] + [len(text)]):
        chunk = text[a:b].strip()
        sid = SESSION_RE.search(chunk)
        if not sid:
            continue
        path = RESULTS_DIR / f"{sid.group(1)}.txt"
        if path.exists():
            continue
        path.write_text(chunk + "\n", encoding="utf-8")
        saved.append(chunk.split("\n", 1)[0])
    return saved


def watch(stop: threading.Event | None = None, on_saved=print, interval: float = 0.5) -> None:
    if sys.platform != "win32":
        return
    last = _user32.GetClipboardSequenceNumber()
    while not (stop and stop.is_set()):
        seq = _user32.GetClipboardSequenceNumber()
        if seq != last:
            last = seq
            text = read_clipboard_text()
            if text and HEADER_RE.search(text) and SESSION_RE.search(text):
                for title in save_results(text):
                    on_saved(title)
        time.sleep(interval)


def start_background(on_saved=print) -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=watch, args=(stop, on_saved), name="clipboard", daemon=True).start()
    return stop


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"Watching clipboard for battle results -> {RESULTS_DIR}  (Ctrl+C to quit)")
    try:
        watch(on_saved=lambda t: print(f"[SONUÇ] kaydedildi: {t}"))
    except KeyboardInterrupt:
        pass
