#!/usr/bin/env python3
from __future__ import annotations

import math
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import MAP_PATH, write_json

MAX_BYTES = 2_000_000
UNIT = 0.2
TOLERANCE = 0.6
SVG_NS = "{http://www.w3.org/2000/svg}"
MAPSVG_NS = "{http://mapsvg.com}"
TOKEN = re.compile(r"[MmLlZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE]-?\d+)?")


def parse_path(d: str) -> list[list[tuple[float, float]]]:
    if re.search(r"[^MmLlZz0-9eE.,\s-]", d):
        raise ValueError("path uses commands other than M, L and Z")
    toks, i = TOKEN.findall(d), 0
    rings, cur, cmd = [], None, None
    cx = cy = sx = sy = 0.0
    while i < len(toks):
        t = toks[i]
        if t in "MmLlZz":
            i += 1
            if t in "Zz":
                if cur:
                    rings.append(cur)
                cur, cx, cy, cmd = None, sx, sy, None
                continue
            if t in "Mm":
                x, y = float(toks[i]), float(toks[i + 1])
                i += 2
                cx, cy = (cx + x, cy + y) if t == "m" else (x, y)
                sx, sy = cx, cy
                if cur:
                    rings.append(cur)
                cur = [(cx, cy)]
                cmd = "l" if t == "m" else "L"
                continue
            cmd = t
            continue
        x, y = float(toks[i]), float(toks[i + 1])
        i += 2
        cx, cy = (cx + x, cy + y) if cmd == "l" else (x, y)
        if cur is None:
            cur = [(cx, cy)]
        else:
            cur.append((cx, cy))
    if cur:
        rings.append(cur)
    return rings


def simplify(pts, eps):
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        best, idx = 0.0, -1
        for j in range(a + 1, b):
            px, py = pts[j]
            dist = math.hypot(px - ax, py - ay) if length < 1e-9 else abs(dy * px - dx * py + bx * ay - by * ax) / length
            if dist > best:
                best, idx = dist, j
        if best > eps:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def encode(pts) -> str:
    q = [(round(x / UNIT), round(y / UNIT)) for x, y in pts]
    out, px, py = [], 0, 0
    for k, (x, y) in enumerate(q):
        out += [x, y] if k == 0 else [x - px, y - py]
        px, py = x, y
    return ",".join(str(v) for v in out)


def build(svg_text: str) -> dict:
    if len(svg_text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("SVG too large")
    if re.search(r"<!(DOCTYPE|ENTITY)", svg_text, re.IGNORECASE):
        raise ValueError("DOCTYPE/ENTITY declarations are not allowed")
    root = ET.fromstring(svg_text)
    geo = root.get(MAPSVG_NS + "geoViewBox")
    if not geo:
        raise ValueError("not a geo-calibrated MapSVG file (missing mapsvg:geoViewBox)")
    west, north, east, south = (float(v) for v in geo.split())
    width, height = float(root.get("width")), float(root.get("height"))
    areas = []
    for el in root.iter(SVG_NS + "path"):
        pid, title, d = el.get("id", ""), el.get("title", ""), el.get("d", "")
        if not re.match(r"^(IE-[A-Z]{1,2}|GB-NIR)$", pid):
            continue
        rings = [encode(simplify(r, TOLERANCE)) for r in parse_path(d)]
        rings = [r for r in rings if r.count(",") >= 7]
        areas.append({"id": pid, "name": re.sub(r"[^A-Za-z .'-]", "", title)[:40], "rings": rings})
    return {
        "source": {"title": "MapSVG Ireland map (geo-calibrated)", "url": "https://mapsvg.com/maps/ireland/",
                   "licence": "CC0 1.0 (public domain dedication)"},
        "width": width, "height": height,
        "geo_bounds": {"west": west, "north": north, "east": east, "south": south},
        "unit": UNIT,
        "encoding": "Each ring is a string of comma-separated integers: the absolute start x,y, then x,y deltas, "
                    "all in multiples of 'unit' SVG pixels. Simplified from the original with Douglas-Peucker (0.6 px).",
        "areas": areas,
    }


def main(argv) -> int:
    if len(argv) != 2:
        print("usage: python3 scripts/build_map.py path/to/ireland.svg")
        return 2
    with open(argv[1], encoding="utf-8") as f:
        data = build(f.read())
    write_json(MAP_PATH, data)
    print(f"Wrote {MAP_PATH} with {len(data['areas'])} areas. Now run: python3 scripts/validate.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
