#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import math
import sys
import urllib.parse

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import SITKA_PATH, write_json
import fetch_updates

LAYER = "https://services7.arcgis.com/6LSAdqgf43oKRpP6/arcgis/rest/services/Coillte_Boundaries_Consultation/FeatureServer/4"
WHERE = "SPP1='SS'"
PAGE = 1000
ORIGIN = {"lat": 51.3, "lng": -10.7}
CELL = {"dlat": 0.05, "dlng": 0.075}
MAX_I, MAX_J = 80, 90
MIN_PLOTS, MAX_PLOTS = 20_000, 200_000


def query(params: dict) -> dict:
    url = LAYER + "/query?" + urllib.parse.urlencode({**params, "f": "json"})
    d = json.loads(fetch_updates.fetch(url, "application/json"))
    if "error" in d:
        raise ValueError(f"service error: {d['error']}")
    return d


def fetch_plots() -> list[tuple[float, float, float]]:
    total = query({"where": WHERE, "returnCountOnly": "true"})["count"]
    if not (MIN_PLOTS <= total <= MAX_PLOTS):
        raise ValueError(f"{total} Sitka plots is outside the expected range")
    plots, offset = [], 0
    while offset < total:
        d = query({"where": WHERE, "outFields": "GIS_AREA,FID", "returnGeometry": "false",
                   "returnCentroid": "true", "outSR": "4326", "orderByFields": "FID",
                   "resultOffset": offset, "resultRecordCount": PAGE})
        feats = d.get("features") or []
        if not feats:
            break
        for f in feats:
            c, a = f.get("centroid") or {}, f.get("attributes") or {}
            lng, lat, ha = c.get("x"), c.get("y"), a.get("GIS_AREA")
            if all(isinstance(v, (int, float)) and math.isfinite(v) for v in (lng, lat, ha)) and 0 < ha < 1000:
                plots.append((lat, lng, float(ha)))
        offset += len(feats)
        print(f"  {offset} / {total}", file=sys.stderr)
    if len(plots) < 0.98 * total:
        raise ValueError(f"only {len(plots)} usable plots out of {total}")
    return plots


def grid(plots) -> dict:
    cells: dict[tuple[int, int], float] = {}
    skipped = 0
    for lat, lng, ha in plots:
        i = math.floor((lng - ORIGIN["lng"]) / CELL["dlng"])
        j = math.floor((lat - ORIGIN["lat"]) / CELL["dlat"])
        if not (0 <= i <= MAX_I and 0 <= j <= MAX_J):
            skipped += 1
            continue
        cells[(i, j)] = cells.get((i, j), 0.0) + ha
    rows = sorted([i, j, round(ha)] for (i, j), ha in cells.items() if round(ha) >= 1)
    return {
        "version": 1,
        "species": "Sitka spruce",
        "source": "Coillte Forest Inventory (main species), CC BY 4.0",
        "source_url": "https://data.gov.ie/en_GB/dataset/coilltepublicboundaries",
        "fetched": dt.date.today().isoformat(),
        "origin": ORIGIN,
        "cell": CELL,
        "plots": len(plots) - skipped,
        "total_ha": sum(r[2] for r in rows),
        "cells": rows,
    }


def main() -> int:
    out = grid(fetch_plots())
    write_json(SITKA_PATH, out)
    print(f"{out['plots']} plots, {out['total_ha']} ha in {len(out['cells'])} cells -> {SITKA_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
