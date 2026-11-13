#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import struct
import sys
import time
import urllib.parse
import zipfile

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import NATIVE_PATH, SITKA_PATH, allowlist, write_json
import fetch_updates

LAYER = "https://services7.arcgis.com/6LSAdqgf43oKRpP6/arcgis/rest/services/Coillte_Boundaries_Consultation/FeatureServer/4"
STOCKED = ("CHF", "MHF", "BHF")
WHERE = "LUT IN ('CHF','MHF','BHF')"
PAGE = 1000
ORIGIN = {"lat": 51.3, "lng": -10.7}
CELL = {"dlat": 0.05, "dlng": 0.075}
MAX_I, MAX_J = 80, 90
MIN_PLOTS, MAX_PLOTS = 20_000, 400_000
NATIVE = {"OAK", "PO", "SO", "BI", "DBI", "SBI", "ALD", "ASH", "HAZ", "HOL", "YEW", "ROW", "RWN",
          "SAL", "WIL", "EWIL", "ELM", "HAW"}
LAYERS = {
    "sitka": {"species": "Sitka spruce", "codes": {"SS"}, "path": SITKA_PATH,
              "method": "Plot area x Sitka spruce share of the plot, stocked forest only"},
    "native": {"species": "Native Irish trees", "codes": NATIVE, "path": NATIVE_PATH,
               "method": "Plot area x share of native species (oak, birch, alder, ash, hazel, holly, yew, rowan, "
                         "willow, elm, hawthorn), stocked forest only; Scots pine and unspecified mixes excluded"},
}
SOURCES = [
    {"name": "Coillte Forest Inventory", "licence": "CC BY 4.0",
     "url": "https://data.gov.ie/en_GB/dataset/coilltepublicboundaries"},
    {"name": "DAFM Private Forest Estate 2023", "licence": "CC BY 4.0",
     "url": "https://data.gov.ie/dataset/dafm-private-forest-estate-2023"},
]
PRIVATE_STEM = "PrivateForests2023_AllFields"
MAX_PRIVATE_RECORDS = 500_000


def itm_to_latlng(e: float, n: float) -> tuple[float, float]:
    a, f = 6378137.0, 1 / 298.257222101
    k0, lat0, lng0, fe, fn = 0.99982, math.radians(53.5), math.radians(-8.0), 600000.0, 750000.0
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)

    def merid(phi):
        return a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi
                    - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * math.sin(2 * phi)
                    + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * math.sin(4 * phi)
                    - (35 * e2 ** 3 / 3072) * math.sin(6 * phi))

    m = merid(lat0) + (n - fn) / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
            + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    s, c, t = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    n1 = a / math.sqrt(1 - e2 * s * s)
    t1, c1 = t * t, ep2 * c * c
    r1 = a * (1 - e2) / (1 - e2 * s * s) ** 1.5
    d = (e - fe) / (n1 * k0)
    lat = phi1 - (n1 * t / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                  + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lng = lng0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                  + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / c
    return math.degrees(lat), math.degrees(lng)


def share(pairs, codes) -> float:
    return min(sum(p for s, p in pairs if s in codes) / 100.0, 1.0)


def query(params: dict, attempts: int = 4) -> dict:
    url = LAYER + "/query?" + urllib.parse.urlencode({**params, "f": "json"})
    if not url.startswith(LAYER + "/query?"):
        raise ValueError("unexpected query URL")
    for attempt in range(1, attempts + 1):
        try:
            d = json.loads(fetch_updates.fetch(url, "application/json"))
        except (OSError, ValueError) as e:
            if attempt == attempts:
                raise
            print(f"  retrying after {type(e).__name__} (attempt {attempt})", file=sys.stderr)
            time.sleep(5 * attempt)
            continue
        if "error" in d:
            raise ValueError(f"service error: {d['error']}")
        return d
    raise RuntimeError("unreachable")


def _split(plot_pairs, lat, lng, area, out):
    for key, layer in LAYERS.items():
        sh = share(plot_pairs, layer["codes"])
        if sh > 0:
            out[key].append((lat, lng, area * sh))


def fetch_coillte() -> dict[str, list]:
    total = query({"where": WHERE, "returnCountOnly": "true"})["count"]
    if not (MIN_PLOTS <= total <= MAX_PLOTS):
        raise ValueError(f"{total} Coillte plots is outside the expected range")
    fields = "GIS_AREA,FID," + ",".join(f"SPP{i},CANOPY{i}" for i in range(1, 5))
    out = {k: [] for k in LAYERS}
    offset = 0
    while offset < total:
        d = query({"where": WHERE, "outFields": fields, "returnGeometry": "false",
                   "returnCentroid": "true", "outSR": "4326", "orderByFields": "FID",
                   "resultOffset": offset, "resultRecordCount": PAGE})
        feats = d.get("features") or []
        if not feats:
            break
        for f in feats:
            c, a = f.get("centroid") or {}, f.get("attributes") or {}
            lng, lat, area = c.get("x"), c.get("y"), a.get("GIS_AREA")
            pairs = [((a.get(f"SPP{i}") or "").strip(), a.get(f"CANOPY{i}") or 0) for i in range(1, 5)]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lng, lat, area)) or not 0 < area < 1000:
                continue
            if not all(isinstance(p, (int, float)) and 0 <= p <= 100 for _, p in pairs):
                continue
            if sum(p for _, p in pairs) == 0 and pairs[0][0]:
                pairs = [(pairs[0][0], 100)]
            _split(pairs, lat, lng, area, out)
        offset += len(feats)
        print(f"  Coillte {offset} / {total}", file=sys.stderr)
    if offset < 0.98 * total:
        raise ValueError(f"only fetched {offset} of {total} Coillte plots")
    return out


def _dbf_rows(data: bytes):
    if len(data) < 32:
        raise ValueError("dbf too short")
    n, hl, rl = struct.unpack("<IHH", data[4:12])
    if n > MAX_PRIVATE_RECORDS or hl > len(data) or rl == 0:
        raise ValueError("dbf header out of range")
    fields, pos = [], 32
    while pos < hl - 1 and data[pos] != 0x0D:
        fields.append((data[pos:pos + 11].split(b"\0")[0].decode("ascii"), data[pos + 16]))
        pos += 32
    for k in range(n):
        r = data[hl + k * rl: hl + (k + 1) * rl]
        if len(r) < rl:
            raise ValueError("dbf truncated")
        if r[:1] == b"*":
            yield None
            continue
        row, p = {}, 1
        for name, length in fields:
            row[name] = r[p:p + length].decode("latin-1").strip()
            p += length
        yield row


def _shp_boxes(data: bytes):
    if len(data) < 100 or struct.unpack(">I", data[:4])[0] != 9994:
        raise ValueError("not a shapefile")
    pos = 100
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0] * 2
        body = data[pos + 8:pos + 8 + length]
        shape = struct.unpack("<i", body[:4])[0] if len(body) >= 4 else 0
        yield struct.unpack("<4d", body[4:36]) if shape in (5, 15, 25) and len(body) >= 36 else None
        pos += 8 + length


def read_private(zip_path: str) -> dict[str, list]:
    with zipfile.ZipFile(zip_path) as z:
        names = {i.filename for i in z.infolist()}
        need = {PRIVATE_STEM + ".shp", PRIVATE_STEM + ".dbf"}
        if not need <= names:
            raise ValueError(f"zip does not contain {sorted(need)}")
        for nm in need:
            if z.getinfo(nm).file_size > 400_000_000:
                raise ValueError(f"{nm} is unexpectedly large")
        shp, dbf = z.read(PRIVATE_STEM + ".shp"), z.read(PRIVATE_STEM + ".dbf")
    out = {k: [] for k in LAYERS}
    for box, row in zip(_shp_boxes(shp), _dbf_rows(dbf)):
        if box is None or row is None or row.get("LUC") not in STOCKED:
            continue
        try:
            area = float(row.get("Area_ha") or 0)
            pairs = [(row.get(f"Sp_{i}", ""), float(row.get(f"SpPerc_{i}") or 0)) for i in range(1, 8)]
        except ValueError:
            continue
        if not (0 < area < 1000) or any(not 0 <= p <= 100 for _, p in pairs):
            continue
        xmin, ymin, xmax, ymax = box
        if not (400_000 <= xmin <= xmax <= 800_000 and 500_000 <= ymin <= ymax <= 1_000_000):
            continue
        lat, lng = itm_to_latlng((xmin + xmax) / 2, (ymin + ymax) / 2)
        _split(pairs, lat, lng, area, out)
    if not (MIN_PLOTS <= len(out["sitka"]) <= MAX_PLOTS):
        raise ValueError(f"{len(out['sitka'])} private Sitka plots is outside the expected range")
    return out


def grid(coillte, private, layer: str = "sitka") -> dict:
    cells: dict[tuple[int, int], float] = {}
    totals = {}
    for key, plots in (("coillte", coillte), ("private", private)):
        kept = 0.0
        for lat, lng, ha in plots:
            i = math.floor((lng - ORIGIN["lng"]) / CELL["dlng"])
            j = math.floor((lat - ORIGIN["lat"]) / CELL["dlat"])
            if 0 <= i <= MAX_I and 0 <= j <= MAX_J:
                cells[(i, j)] = cells.get((i, j), 0.0) + ha
                kept += ha
        totals[key] = round(kept)
    rows = sorted([i, j, round(ha)] for (i, j), ha in cells.items() if round(ha) >= 1)
    return {
        "version": 2,
        "species": LAYERS[layer]["species"],
        "method": LAYERS[layer]["method"],
        "sources": SOURCES,
        "fetched": dt.date.today().isoformat(),
        "origin": ORIGIN,
        "cell": CELL,
        "plots": len(coillte) + len(private),
        "coillte_ha": totals.get("coillte", 0),
        "private_ha": totals.get("private", 0),
        "total_ha": sum(r[2] for r in rows),
        "cells": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--private", required=True, help="path to privateforests2023.zip from data.gov.ie")
    args = ap.parse_args(argv)
    fetch_updates.FETCH_HOSTS = allowlist()["layer_fetch_hosts"]
    private = read_private(args.private)
    for key in LAYERS:
        print(f"private {key}: {len(private[key])} plots, {round(sum(p[2] for p in private[key]))} ha", file=sys.stderr)
    coillte = fetch_coillte()
    for key, layer in LAYERS.items():
        out = grid(coillte[key], private[key], key)
        write_json(layer["path"], out)
        print(f"{key}: {out['plots']} plots, {out['total_ha']} ha in {len(out['cells'])} cells "
              f"(Coillte {out['coillte_ha']}, private {out['private_ha']}) -> {layer['path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
