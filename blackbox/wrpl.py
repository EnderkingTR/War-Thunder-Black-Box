"""War Thunder replay (.wrpl) reader - header, packet stream, results, kill reports.

Reads replay files the game writes to disk; never touches the game process.
Format knowledge from public community research (WTACRP docs, wrpl-inspector);
this code is written independently. Offsets are build-specific: verify on new versions.

Requires Python 3.14+ for compression.zstd (standard library).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path

MAGIC = 0x1000ACE5
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

PKT_END, PKT_START, PKT_AIRCRAFT, PKT_CHAT, PKT_MPI = 0, 1, 2, 3, 4

MSG_KILL = 0xF058
MSG_CRIT = 0xF056
MSG_SEVERE = 0xF157


def _cstr(b: bytes, off: int, n: int) -> str:
    raw = b[off:off + n]
    return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")


@dataclass
class Header:
    version: int
    level: str
    level_settings: str
    battle_type: str
    environment: str
    visibility: str
    rez_offset: int
    difficulty: int
    session_id: str
    settings_size: int
    loc_name: str
    start_time: int
    time_limit: int
    score_limit: int
    battle_class: str

    @property
    def map_id(self) -> str:
        """'levels/spain.bin' -> 'spain'"""
        return self.level.rsplit("/", 1)[-1].removesuffix(".bin")


def parse_header(b: bytes) -> Header:
    if len(b) < 1226 or struct.unpack_from("<I", b, 0)[0] != MAGIC:
        raise ValueError("not a wrpl file")
    u32 = lambda o: struct.unpack_from("<I", b, o)[0]
    return Header(
        version=u32(4),
        level=_cstr(b, 8, 128),
        level_settings=_cstr(b, 136, 260),
        battle_type=_cstr(b, 396, 128),
        environment=_cstr(b, 524, 128),
        visibility=_cstr(b, 652, 32),
        rez_offset=u32(684),
        difficulty=b[688] & 0x0F,
        session_id=f"{struct.unpack_from('<Q', b, 732)[0]:016x}",
        settings_size=u32(748),
        loc_name=_cstr(b, 780, 128),
        start_time=u32(908),
        time_limit=u32(912),
        score_limit=u32(916),
        battle_class=_cstr(b, 968, 128),
    )


# ------------------------------------------------------------------ packets
def _read_vlq(buf: bytes, p: int) -> tuple[int, int]:
    b = buf[p]
    if b & 0x80:
        return b & 0x7F, p + 1
    if b & 0x40:
        return ((b << 8) | buf[p + 1]) ^ 0x4000, p + 2
    if b & 0x20:
        return ((b << 16) | (buf[p + 1] << 8) | buf[p + 2]) ^ 0x200000, p + 3
    if b & 0x10:
        return ((b << 24) | (buf[p + 1] << 16) | (buf[p + 2] << 8) | buf[p + 3]) ^ 0x10000000, p + 4
    return struct.unpack_from("<I", buf, p + 1)[0], p + 5


def decompress_stream(b: bytes, h: Header) -> bytes:
    start = 1226 + h.settings_size
    end = h.rez_offset if h.rez_offset > start else len(b)
    i = b.find(ZSTD_MAGIC, start, end)
    if i >= 0:
        from compression import zstd  # Python 3.14+
        return zstd.decompress(b[i:end])
    # older replays: zlib
    for j in range(start, min(start + 64, end)):
        if b[j] == 0x78:
            try:
                return zlib.decompressobj().decompress(b[j:end])
            except zlib.error:
                continue
    raise ValueError("packet stream not found")


def iter_packets(buf: bytes):
    """Yields (ptype, ms, payload)."""
    p, last_ms = 0, 0
    n = len(buf)
    while p < n:
        size, p = _read_vlq(buf, p)
        body = buf[p:p + size]
        p += size
        if not body:
            continue
        t = body[0]
        if t & 0x10:
            ptype, ms, payload = t ^ 0x10, last_ms, body[2:]
        else:
            if len(body) < 6:
                continue
            ptype, ms, payload = t, struct.unpack_from("<I", body, 2)[0], body[6:]
        last_ms = ms
        yield ptype, ms, payload


# ------------------------------------------------------------- bit reader
class BitReader:
    """MSB-first bit reader."""

    def __init__(self, data: bytes) -> None:
        self.d = data
        self.off = 0  # in bits

    def bits(self, n: int) -> int:
        v = 0
        for _ in range(n):
            byte = self.d[self.off >> 3]
            v = (v << 1) | ((byte >> (7 - (self.off & 7))) & 1)
            self.off += 1
        return v

    def u8(self) -> int:
        return self.bits(8)

    def bytes_(self, n: int) -> bytes:
        return bytes(self.u8() for _ in range(n))

    def u16le(self) -> int:
        a, b = self.u8(), self.u8()
        return a | (b << 8)

    def u32le(self) -> int:
        return struct.unpack("<I", self.bytes_(4))[0]

    def leb128(self) -> int:
        v, shift = 0, 0
        while True:
            b = self.u8()
            v |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                return v

    def lenstr(self) -> str:
        n = self.u8()
        return self.bytes_(n).decode("utf-8", errors="replace")


_SIZE_CODES = {1: 1, 2: 8, 3: 16, 4: 32, 5: 64, 6: 96, 7: 128}


def read_id_fields(data: bytes, readers: dict) -> dict:
    """IdFieldSerializer32: u16 size-table offset, LEB128 field mask, fields, size table."""
    r = BitReader(data)
    size_table_off = r.u16le()
    mask = r.leb128()
    body_start = r.off
    present = [i for i in range(64) if mask >> i & 1]
    r.off = size_table_off * 8
    sizes = []
    for _ in present:
        h = r.bits(3)
        sizes.append(_SIZE_CODES[h] if h else r.leb128())
    r.off = body_start
    out = {}
    for i, width in zip(present, sizes):
        start = r.off
        if i in readers:
            out[i] = readers[i](r)
        r.off = start + width
    return out


_KILL_FIELDS = {
    1: BitReader.u32le,     # killer pid
    2: BitReader.lenstr,    # killer vehicle
    3: lambda r: r.u16le() & 0x7FF,  # victim uid
    4: lambda r: r.u16le() & 0x7FF,  # killer uid
    0xA: BitReader.lenstr,  # weapon
    0xB: BitReader.u32le,   # victim pid
    0xC: BitReader.lenstr,  # destroyed weapon (e.g. a shot-down missile)
}


@dataclass
class KillReport:
    ms: int
    killer_pid: int | None
    killer_vehicle: str | None
    victim_pid: int | None
    weapon: str | None
    destroyed_weapon: str | None
    killer_uid: int | None
    victim_uid: int | None


def _mpi_id(payload: bytes) -> int | None:
    if len(payload) < 4:
        return None
    return payload[2] | (payload[3] << 8)


# ------------------------------------------------------------------ FAT BLK
def _uleb(b: bytes, p: int) -> tuple[int, int]:
    v, shift = 0, 0
    while True:
        x = b[p]
        p += 1
        v |= (x & 0x7F) << shift
        shift += 7
        if not x & 0x80:
            return v, p


def parse_fat_blk(raw: bytes) -> dict:
    """Binary FAT BLK -> nested dict. Repeated names become lists."""
    if not raw or raw[0] != 0x01:
        raise ValueError("not a FAT blk")
    b, p = raw[1:], 0
    n_names, p = _uleb(b, p)
    names_size, p = _uleb(b, p)
    names = b[p:p + names_size].split(b"\0")[:n_names]
    names = [n.decode("utf-8", errors="replace") for n in names]
    p += names_size
    n_blocks, p = _uleb(b, p)
    n_params, p = _uleb(b, p)
    params_size, p = _uleb(b, p)
    pdata = b[p:p + params_size]
    p += params_size
    pinfo = b[p:p + n_params * 8]
    p += n_params * 8

    def value(typ, data, ofs):
        if typ == 1:  # string
            inline = bool(data & 0x80000000)
            o = data & 0x7FFFFFFF
            if inline:
                return _cstr(struct.pack("<I", o), 0, 4)
            return pdata[o:pdata.find(b"\0", o)].decode("utf-8", errors="replace")
        if typ == 2:
            return struct.unpack("<i", struct.pack("<I", data))[0]
        if typ == 3:
            return struct.unpack("<f", struct.pack("<I", data))[0]
        if typ == 9:
            return bool(data)
        if typ == 10:
            return data
        sizes = {4: ("<2f", 8), 5: ("<3f", 12), 6: ("<4f", 16), 7: ("<2i", 8), 8: ("<3i", 12),
                 11: ("<12f", 48), 12: ("<q", 8)}
        if typ in sizes:
            fmt, n = sizes[typ]
            return list(struct.unpack(fmt, pdata[data:data + n])) if typ != 12 else \
                struct.unpack(fmt, pdata[data:data + n])[0]
        return None

    params = []
    for i in range(n_params):
        name_id = pinfo[i * 8] | (pinfo[i * 8 + 1] << 8) | (pinfo[i * 8 + 2] << 16)
        typ = pinfo[i * 8 + 3]
        data = struct.unpack_from("<I", pinfo, i * 8 + 4)[0]
        params.append((names[name_id] if name_id < len(names) else f"#{name_id}", value(typ, data, 0)))

    blocks = []
    for _ in range(n_blocks):
        name_id, p = _uleb(b, p)
        pc, p = _uleb(b, p)
        cc, p = _uleb(b, p)
        first = 0
        if cc:
            first, p = _uleb(b, p)
        blocks.append((name_id, pc, cc, first))

    def put(d, k, v):
        if k in d:
            if not isinstance(d[k], list) or not d.get(f"__list_{k}"):
                d[k] = [d[k]]
                d[f"__list_{k}"] = True
            d[k].append(v)
        else:
            d[k] = v

    built = [dict() for _ in blocks]
    pi = 0
    for bi, (_, pc, _, _) in enumerate(blocks):
        for k, v in params[pi:pi + pc]:
            put(built[bi], k, v)
        pi += pc
    for bi, (_, _, cc, first) in enumerate(blocks):
        for ci in range(first, first + cc):
            nid = blocks[ci][0]
            put(built[bi], names[nid - 1] if nid else "root", built[ci])

    def clean(x):
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items() if not k.startswith("__list_")}
        if isinstance(x, list):
            return [clean(v) for v in x]
        return x

    return clean(built[0]) if built else {}


# ------------------------------------------------------------------ replay
@dataclass
class Replay:
    path: Path
    header: Header
    results: dict | None = None
    kills: list[KillReport] = field(default_factory=list)
    crits: list[dict] = field(default_factory=list)
    severe: list[dict] = field(default_factory=list)
    chat_packets: int = 0
    end_ms: int | None = None
    mpi_counts: dict = field(default_factory=dict)


def load(path: Path, packets: bool = True) -> Replay:
    b = Path(path).read_bytes()
    h = parse_header(b)
    rp = Replay(Path(path), h)
    if 0 < h.rez_offset < len(b):
        try:
            rp.results = parse_fat_blk(b[h.rez_offset:])
        except (ValueError, IndexError, struct.error):
            rp.results = None
    if not packets:
        return rp
    stream = decompress_stream(b, h)
    dmg_fields = {2: BitReader.u32le, 3: BitReader.lenstr}
    for ptype, ms, pl in iter_packets(stream):
        if ptype == PKT_END:
            rp.end_ms = ms
        elif ptype == PKT_CHAT:
            rp.chat_packets += 1
        elif ptype == PKT_MPI:
            mid = _mpi_id(pl)
            rp.mpi_counts[mid] = rp.mpi_counts.get(mid, 0) + 1
            try:
                if mid == MSG_KILL:
                    f = read_id_fields(pl[4:], _KILL_FIELDS)
                    none32 = lambda v: None if v in (None, 0xFFFFFFFF) else v
                    none11 = lambda v: None if v in (None, 0x7FF) else v
                    rp.kills.append(KillReport(ms, none32(f.get(1)), f.get(2) or None, none32(f.get(0xB)),
                                               f.get(0xA) or None, f.get(0xC) or None,
                                               none11(f.get(4)), none11(f.get(3))))
                elif mid in (MSG_CRIT, MSG_SEVERE):
                    f = read_id_fields(pl[4:], dmg_fields)
                    (rp.crits if mid == MSG_CRIT else rp.severe).append(
                        {"ms": ms, "pid": f.get(2), "vehicle": f.get(3)})
            except (IndexError, KeyError, struct.error):
                pass
    return rp
