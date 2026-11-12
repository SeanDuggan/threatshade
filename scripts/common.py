"""Shared helpers for the Threatshade data pipeline. Standard library only."""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "site" / "data" / "data.json"
STATE_DIR = ROOT / "data" / "state"
REPORT_PATH = ROOT / "reports" / "update-report.md"
ALLOWLIST_PATH = ROOT / "config" / "link_allowlist.json"

TOP_EMITTER = 12_300_000
CATS = {"climate": 30, "water": 25, "air": 10, "enforce": 20, "habitat": 15}


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)  # atomic on the same filesystem


def allowlist() -> dict:
    return load_json(ALLOWLIST_PATH)


def host_allowed(url: str, hosts: list[str]) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        return False
    h = parts.hostname.lower()
    return any(h == a or h.endswith("." + a) for a in hosts)


# ---- scoring: must mirror site/app.js (tests check both agree on known values) ----
def climate_pts(tonnes) -> float:
    if not tonnes:
        return 0.0
    x = (math.log10(tonnes) - 4) / (math.log10(TOP_EMITTER) - 4)
    return max(0.0, min(1.0, x)) * 30


def enforce_pts(e: dict) -> float:
    v = {"current": 10, "past": 5}.get(e.get("nps"), 0)
    v += min(15, 3 * e.get("prosecutions", 0))
    v += min(4, 2 * e.get("stop_orders", 0))
    v += 6 if e.get("big_fine") else 0
    return float(min(20, v))


def score(p: dict) -> float:
    pts = {
        "climate": climate_pts(p.get("co2_tonnes")),
        "water": p["points"]["water"],
        "air": p["points"]["air"],
        "enforce": enforce_pts(p["enforcement"]),
        "habitat": p["points"]["habitat"],
    }
    return sum(pts.values()) / sum(CATS.values()) * 100


# ---- name matching for EPA lists ----
_SUFFIXES = re.compile(r"\b(limited|ltd|unlimited company|unlimited|plc|dac|company|co-operative|co-op|coop|society|the)\b")


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)
    s = _SUFFIXES.sub(" ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def names_match(a: str, b: str) -> bool:
    """Loose match: same name, or one name is the start of the other. Used only to decide
    whether a listed site is already covered by the board (for reporting), never to change data."""
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    return na == nb or na.startswith(nb + " ") or nb.startswith(na + " ")


def match_kind(board_name: str, listed_name: str) -> str | None:
    """How confidently a board entry matches a name on an EPA list.

    "exact":    same name after normalising, and the board name has no "(...)" qualifier.
                Only this is safe to act on automatically.
    "possible": a loose match, or the board entry is qualified to one site or owner
                (e.g. "Kingspan (Kingscourt)"), so a different site of the same company could
                be the one listed. A human must check.
    None:       no match.
    """
    if not names_match(board_name, listed_name):
        return None
    if norm_name(board_name) == norm_name(listed_name) and "(" not in board_name:
        return "exact"
    return "possible"


# ---- county map (site/data/ireland-map.json) ----
MAP_PATH = ROOT / "site" / "data" / "ireland-map.json"
RING_RE = re.compile(r"^-?\d{1,5}(,-?\d{1,5})*$")


def decode_ring(ring: str, unit: float) -> list[tuple[float, float]]:
    """Delta-encoded integer ring -> list of (x, y) in SVG pixels."""
    nums = [int(v) for v in ring.split(",")]
    pts, x, y = [], 0, 0
    for i in range(0, len(nums) - 1, 2):
        x, y = (nums[i], nums[i + 1]) if i == 0 else (x + nums[i], y + nums[i + 1])
        pts.append((x * unit, y * unit))
    return pts


def _merc(lat: float) -> float:
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def project(m: dict, lat: float, lng: float) -> tuple[float, float]:
    """Lat/lng -> SVG pixels. The MapSVG file is Web Mercator within its geo bounds
    (checked against 33 towns: all inland ones land in the right county). Mirrors projFor() in app.js."""
    g = m["geo_bounds"]
    x = (lng - g["west"]) / (g["east"] - g["west"]) * m["width"]
    y = (_merc(g["north"]) - _merc(lat)) / (_merc(g["north"]) - _merc(g["south"])) * m["height"]
    return x, y


def point_in_ring(x: float, y: float, pts) -> bool:
    inside, j = False, len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def area_at(m: dict, lat: float, lng: float):
    """Return the area (county) dict containing the point, or None (e.g. offshore)."""
    x, y = project(m, lat, lng)
    for a in m["areas"]:
        if any(point_in_ring(x, y, decode_ring(r, m["unit"])) for r in a["rings"]):
            return a
    return None
