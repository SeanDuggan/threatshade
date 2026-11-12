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
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return False
    return na == nb or na.startswith(nb + " ") or nb.startswith(na + " ")
