#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import (DATA_PATH, MAP_PATH, REPORT_PATH, RING_RE, ROOT, NATIVE_PATH, SITKA_PATH, allowlist, area_at,
                    decode_ring, host_allowed, load_json, score)

SECTORS = {"Water utility", "Dairy & food", "Chemicals", "Heavy industry", "Power", "Aviation",
           "Manufacturing", "Waste", "Land use"}
ID_RE = re.compile(r"^[a-z0-9-]{2,40}$")
BAD_TEXT = re.compile(r"[<>\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|javascript:|data:", re.IGNORECASE)
SCORE_SWING_WARN = 15.0
MAX_BYTES = 1_000_000


class Result:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def _text(r: Result, where: str, v, max_len: int, required=True):
    if v is None and not required:
        return
    if not isinstance(v, str) or not v.strip():
        r.err(f"{where}: must be a non-empty string")
        return
    if len(v) > max_len:
        r.err(f"{where}: longer than {max_len} characters")
    if BAD_TEXT.search(v):
        r.err(f"{where}: contains disallowed characters or markup")


def _num(r: Result, where: str, v, lo, hi, integer=False, allow_none=False):
    if v is None and allow_none:
        return
    ok = isinstance(v, int) if integer else isinstance(v, (int, float))
    if isinstance(v, bool) or not ok or not (lo <= v <= hi):
        r.err(f"{where}: must be a {'whole number' if integer else 'number'} between {lo} and {hi}")


def validate(data, r: Result | None = None) -> Result:
    r = r or Result()
    hosts = allowlist()["link_hosts"]
    if not isinstance(data, dict):
        r.err("top level must be an object")
        return r
    extra = set(data) - {"schema_version", "last_reviewed", "sources", "polluters"}
    if extra:
        r.err(f"unexpected top-level keys: {sorted(extra)}")
    if data.get("schema_version") != 1:
        r.err("schema_version must be 1")
    try:
        dt.date.fromisoformat(str(data.get("last_reviewed")))
    except ValueError:
        r.err("last_reviewed must be an ISO date (YYYY-MM-DD)")

    src_ids = set()
    for i, s in enumerate(data.get("sources") or []):
        w = f"sources[{i}]"
        _num(r, w + ".id", s.get("id"), 1, 9999, integer=True)
        if s.get("id") in src_ids:
            r.err(f"{w}: duplicate id {s.get('id')}")
        src_ids.add(s.get("id"))
        _text(r, w + ".title", s.get("title"), 300)
        if not isinstance(s.get("url"), str) or not host_allowed(s["url"], hosts):
            r.err(f"{w}.url: must be https on an allowlisted host (config/link_allowlist.json)")
    if not src_ids:
        r.err("sources must not be empty")

    pol = data.get("polluters") or []
    if not (1 <= len(pol) <= 500):
        r.err("polluters must contain between 1 and 500 entries")
    seen = set()
    for i, p in enumerate(pol):
        w = f"polluters[{i}]"
        pid = p.get("id")
        if not isinstance(pid, str) or not ID_RE.match(pid):
            r.err(f"{w}.id: lowercase letters, digits and hyphens only")
        if pid in seen:
            r.err(f"{w}: duplicate id {pid}")
        seen.add(pid)
        w = f"polluter '{pid}'"
        _text(r, w + ".name", p.get("name"), 120)
        if p.get("sector") not in SECTORS:
            r.err(f"{w}.sector: must be one of {sorted(SECTORS)}")
        _num(r, w + ".co2_tonnes", p.get("co2_tonnes"), 0, 50_000_000, allow_none=True)
        _num(r, w + ".co2_year", p.get("co2_year"), 2015, 2035, integer=True, allow_none=True)
        if not isinstance(p.get("co2_estimated"), bool):
            r.err(f"{w}.co2_estimated: must be true or false")
        pts = p.get("points") or {}
        _num(r, w + ".points.water", pts.get("water"), 0, 25)
        _num(r, w + ".points.air", pts.get("air"), 0, 10)
        _num(r, w + ".points.habitat", pts.get("habitat"), 0, 15)
        e = p.get("enforcement") or {}
        if e.get("nps") not in (None, "current", "past"):
            r.err(f"{w}.enforcement.nps: must be null, 'current' or 'past'")
        _num(r, w + ".enforcement.prosecutions", e.get("prosecutions"), 0, 500, integer=True)
        _num(r, w + ".enforcement.stop_orders", e.get("stop_orders"), 0, 50, integer=True)
        if not isinstance(e.get("big_fine"), bool):
            r.err(f"{w}.enforcement.big_fine: must be true or false")
        for k, v in (p.get("flags") or {}).items():
            if k not in ("rising", "restoring", "raw_sewage") or not isinstance(v, bool):
                r.err(f"{w}.flags.{k}: unknown flag or not a boolean")
        for j, b in enumerate(p.get("extra_badges") or []):
            _text(r, f"{w}.extra_badges[{j}].label", b.get("label"), 40)
        sites = p.get("sites") or []
        if not (1 <= len(sites) <= 20):
            r.err(f"{w}.sites: between 1 and 20 sites required")
        for j, s in enumerate(sites):
            _text(r, f"{w}.sites[{j}].name", s.get("name"), 120)
            _num(r, f"{w}.sites[{j}].lat", s.get("lat"), 51.3, 55.5)
            _num(r, f"{w}.sites[{j}].lng", s.get("lng"), -10.7, -5.4)
        ev = p.get("evidence") or []
        if not (1 <= len(ev) <= 25):
            r.err(f"{w}.evidence: between 1 and 25 items required (every score needs a source)")
        for j, x in enumerate(ev):
            _text(r, f"{w}.evidence[{j}].date", x.get("date"), 30)
            _text(r, f"{w}.evidence[{j}].text", x.get("text"), 600)
            if x.get("source") not in src_ids:
                r.err(f"{w}.evidence[{j}].source: refers to unknown source id {x.get('source')}")
        _text(r, w + ".note", p.get("note"), 600, required=False)
        for j, lic in enumerate(p.get("epa_licences") or []):
            if not isinstance(lic, str) or not re.match(r"^[A-Z]\d{4}-\d{2}$", lic):
                r.err(f"{w}.epa_licences[{j}]: expected an EPA register number like P0065-01")
        basis = p.get("points_basis")
        if basis is not None:
            if not isinstance(basis, dict) or set(basis) - {"water", "air", "habitat", "reviewed"}:
                r.err(f"{w}.points_basis: only water, air, habitat and reviewed are allowed")
            else:
                for k in ("water", "air", "habitat"):
                    _text(r, f"{w}.points_basis.{k}", basis.get(k), 400)
                if not isinstance(basis.get("reviewed"), bool):
                    r.err(f"{w}.points_basis.reviewed: must be true or false")

    if r.errors:
        return r
    used = {x["source"] for p in pol for x in p["evidence"]}
    for sid in sorted(src_ids - used):
        r.warn(f"source {sid} is not cited by any polluter")
    return r


AREA_ID_RE = re.compile(r"^(IE-[A-Z]{1,2}|GB-NIR)$")
MAP_MAX_BYTES = 300_000


def validate_map(m, r: Result | None = None) -> Result:
    r = r or Result()
    if not isinstance(m, dict):
        r.err("map: top level must be an object")
        return r
    allowed = {"source", "width", "height", "geo_bounds", "unit", "encoding", "areas"}
    if set(m) - allowed:
        r.err(f"map: unexpected keys {sorted(set(m) - allowed)}")
    _num(r, "map.width", m.get("width"), 100, 2000)
    _num(r, "map.height", m.get("height"), 100, 2000)
    _num(r, "map.unit", m.get("unit"), 0.01, 1)
    g = m.get("geo_bounds") or {}
    _num(r, "map.geo_bounds.west", g.get("west"), -11, -10)
    _num(r, "map.geo_bounds.east", g.get("east"), -6, -5)
    _num(r, "map.geo_bounds.north", g.get("north"), 55, 56)
    _num(r, "map.geo_bounds.south", g.get("south"), 51, 52)
    if r.errors:
        return r
    areas = m.get("areas") or []
    if not (20 <= len(areas) <= 40):
        r.err("map: expected 20 to 40 areas")
    ids = set()
    for i, a in enumerate(areas):
        w = f"map.areas[{i}]"
        if set(a) - {"id", "name", "rings"}:
            r.err(f"{w}: unexpected keys")
        if not isinstance(a.get("id"), str) or not AREA_ID_RE.match(a["id"]) or a["id"] in ids:
            r.err(f"{w}.id: must be a unique ISO code like IE-CO or GB-NIR")
        ids.add(a.get("id"))
        _text(r, w + ".name", a.get("name"), 40)
        rings = a.get("rings") or []
        if not (1 <= len(rings) <= 50):
            r.err(f"{w}.rings: between 1 and 50 rings required")
        for j, ring in enumerate(rings):
            if not isinstance(ring, str) or len(ring) > 40_000 or not RING_RE.match(ring):
                r.err(f"{w}.rings[{j}]: must be comma-separated integers only")
                continue
            if ring.count(",") % 2 == 0 or ring.count(",") < 7:
                r.err(f"{w}.rings[{j}]: needs an even count of at least 8 numbers")
                continue
            for x, y in decode_ring(ring, m["unit"]):
                if not (-5 <= x <= m["width"] + 5 and -5 <= y <= m["height"] + 5):
                    r.err(f"{w}.rings[{j}]: point outside the map bounds")
                    break
    return r


SITKA_MAX_BYTES = 200_000
SITKA_CELL_MAX_HA = 3000


def validate_tree_grid(g, r: Result | None = None, label: str = "sitka") -> Result:
    r = r or Result()
    if not isinstance(g, dict):
        r.err(f"{label}: top level must be an object")
        return r
    allowed = {"version", "species", "method", "sources", "fetched", "origin", "cell", "plots",
               "coillte_ha", "private_ha", "total_ha", "cells"}
    if set(g) - allowed:
        r.err(f"{label}: unexpected keys {sorted(set(g) - allowed)}")
    if g.get("version") != 2:
        r.err(f"{label}.version must be 2")
    _text(r, f"{label}.species", g.get("species"), 40)
    _text(r, f"{label}.method", g.get("method"), 250)
    srcs = g.get("sources")
    if not isinstance(srcs, list) or not (1 <= len(srcs) <= 5):
        r.err(f"{label}.sources: between 1 and 5 sources required")
        srcs = []
    for k, s in enumerate(srcs):
        if not isinstance(s, dict) or set(s) - {"name", "licence", "url"}:
            r.err(f"{label}.sources[{k}]: must have only name, licence and url")
            continue
        _text(r, f"{label}.sources[{k}].name", s.get("name"), 80)
        _text(r, f"{label}.sources[{k}].licence", s.get("licence"), 30)
        if not isinstance(s.get("url"), str) or not host_allowed(s["url"], allowlist()["link_hosts"]):
            r.err(f"{label}.sources[{k}].url: must be https on an allowlisted host")
    _num(r, f"{label}.coillte_ha", g.get("coillte_ha"), 0, 1_000_000, integer=True)
    _num(r, f"{label}.private_ha", g.get("private_ha"), 0, 1_000_000, integer=True)
    try:
        dt.date.fromisoformat(str(g.get("fetched")))
    except ValueError:
        r.err(f"{label}.fetched must be an ISO date")
    o, c = g.get("origin") or {}, g.get("cell") or {}
    _num(r, f"{label}.origin.lat", o.get("lat"), 51, 52)
    _num(r, f"{label}.origin.lng", o.get("lng"), -11, -10)
    _num(r, f"{label}.cell.dlat", c.get("dlat"), 0.01, 0.2)
    _num(r, f"{label}.cell.dlng", c.get("dlng"), 0.01, 0.3)
    _num(r, f"{label}.plots", g.get("plots"), 0, 500_000, integer=True)
    cells = g.get("cells")
    if not isinstance(cells, list) or not (1 <= len(cells) <= 8000):
        r.err(f"{label}.cells: between 1 and 8000 cells required")
        return r
    seen, total = set(), 0
    for k, cell in enumerate(cells):
        ok = (isinstance(cell, list) and len(cell) == 3 and all(isinstance(v, int) and not isinstance(v, bool) for v in cell)
              and 0 <= cell[0] <= 80 and 0 <= cell[1] <= 90 and 1 <= cell[2] <= SITKA_CELL_MAX_HA)
        if not ok:
            r.err(f"{label}.cells[{k}]: must be [column 0-80, row 0-90, hectares 1-{SITKA_CELL_MAX_HA}]")
            continue
        if (cell[0], cell[1]) in seen:
            r.err(f"{label}.cells[{k}]: duplicate cell")
        seen.add((cell[0], cell[1]))
        total += cell[2]
    if not r.errors and g.get("total_ha") != total:
        r.err(f"{label}.total_ha does not match the sum of the cells")
    if not r.errors and abs(g["coillte_ha"] + g["private_ha"] - total) > max(50, 0.01 * total):
        r.err(f"{label}.coillte_ha + private_ha does not match total_ha")
    return r


def check_sites_on_land(data, m, r: Result) -> Result:
    for p in data.get("polluters", []):
        for s in p.get("sites", []):
            if area_at(m, s["lat"], s["lng"]) is None:
                r.warn(f"Site '{s['name']}' ({p['name']}) does not fall inside any county on the map; check its coordinates")
    return r


def compare(old, new, r: Result) -> Result:
    o = {p["id"]: p for p in old.get("polluters", [])}
    n = {p["id"]: p for p in new.get("polluters", [])}
    for pid in sorted(set(o) - set(n)):
        r.warn(f"REMOVED polluter: {o[pid]['name']}")
    for pid in sorted(set(n) - set(o)):
        r.warn(f"ADDED polluter: {n[pid]['name']} (score {score(n[pid]):.0f}); check every claim against its sources")
    for pid in sorted(set(o) & set(n)):
        a, b = score(o[pid]), score(n[pid])
        if abs(a - b) >= SCORE_SWING_WARN:
            r.warn(f"LARGE SCORE CHANGE: {n[pid]['name']} {a:.0f} -> {b:.0f}")
        if o[pid]["enforcement"].get("nps") != n[pid]["enforcement"].get("nps"):
            r.warn(f"Priority-list status changed for {n[pid]['name']}: {o[pid]['enforcement'].get('nps')} -> {n[pid]['enforcement'].get('nps')}")
        if o[pid]["name"] != n[pid]["name"]:
            r.warn(f"Name changed: {o[pid]['name']} -> {n[pid]['name']}")
    return r


def load_baseline(args):
    if args.baseline:
        return load_json(args.baseline)
    if args.baseline_ref:
        if not re.match(r"^[A-Za-z0-9._][A-Za-z0-9._/-]{0,99}$", args.baseline_ref):
            raise SystemExit("invalid --baseline-ref")
        rel = DATA_PATH.relative_to(ROOT).as_posix()
        out = subprocess.run(["git", "show", f"{args.baseline_ref}:{rel}"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8", check=False)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA_PATH))
    ap.add_argument("--baseline")
    ap.add_argument("--baseline-ref")
    ap.add_argument("--report", help="append findings to this markdown file")
    args = ap.parse_args(argv)

    raw = open(args.data, "rb").read()
    if len(raw) > MAX_BYTES:
        print(f"ERROR: data file larger than {MAX_BYTES} bytes")
        return 1
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"ERROR: not valid UTF-8 JSON: {e}")
        return 1

    r = validate(data)
    if len(MAP_PATH.read_bytes()) > MAP_MAX_BYTES:
        r.err("map file too large")
    else:
        m = load_json(MAP_PATH)
        validate_map(m, r)
        if not r.errors:
            check_sites_on_land(data, m, r)
    for label, path in (("sitka", SITKA_PATH), ("native", NATIVE_PATH)):
        if not path.exists():
            r.err(f"{label} grid file missing (run scripts/build_tree_layers.py)")
        elif len(path.read_bytes()) > SITKA_MAX_BYTES:
            r.err(f"{label} grid file too large")
        else:
            validate_tree_grid(load_json(path), r, label)
    base = None if r.errors else load_baseline(args)
    if base is not None:
        compare(base, data, r)

    lines = ["## Validation", ""]
    lines += [f"- ERROR: {e}" for e in r.errors] or ["- No errors."]
    lines += [f"- WARNING: {w}" for w in r.warnings]
    text = "\n".join(lines) + "\n"
    print(text)
    if args.report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "a", encoding="utf-8") as f:
            f.write("\n" + text)
    return 1 if r.errors else 0


if __name__ == "__main__":
    sys.exit(main())
