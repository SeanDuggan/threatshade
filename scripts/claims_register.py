#!/usr/bin/env python3
from __future__ import annotations

import csv
import datetime as dt
import re
import sys
from html.parser import HTMLParser

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import DATA_PATH, ROOT, climate_pts, enforce_pts, load_json, score

OUT_DIR = ROOT / "reports"
TIERS = [(50, "Critical"), (35, "High"), (22, "Elevated"), (0, "Watch")]

BADGE_RULES = [
    ("On EPA watchlist", "on the EPA National Priority Sites list now (enforcement.nps = current)",
     lambda p: p["enforcement"].get("nps") == "current"),
    ("Raw sewage", "flags.raw_sewage is true", lambda p: p["flags"].get("raw_sewage")),
    ("Carbon heavyweight", "reported or estimated CO2 of 1 Mt a year or more", lambda p: (p.get("co2_tonnes") or 0) >= 1_000_000),
    ("Repeat offender", "2 or more prosecutions counted", lambda p: p["enforcement"].get("prosecutions", 0) >= 2),
    ("Six-figure penalty", "enforcement.big_fine is true (a fine or penalty of EUR 100,000 or more)", lambda p: p["enforcement"].get("big_fine")),
    ("Emissions rising", "flags.rising is true", lambda p: p["flags"].get("rising")),
    ("Next to protected waters", "habitat points of 12 or more, sector not Land use",
     lambda p: p["points"]["habitat"] >= 12 and p["sector"] != "Land use"),
]

QUESTIONS = [
    "Labels and headings: is it safe to call entries 'Ireland's worst polluters', to score them with a 'Damage Score', and to use the tier names 'Critical', 'High', 'Elevated' and 'Watch'? Should these be framed more clearly as our own index or opinion?",
    "'Repeat offender' is shown when an entry has 2 or more prosecutions counted. Every counted case should have ended in a conviction or guilty plea. Is that enough, and is the word itself acceptable?",
    "Probation Act outcomes (for example Coillte at Glenaboy, Tirlan at Lough Egish) are counted as prosecutions, and the evidence says 'pleaded guilty; Probation Act applied', never 'convicted'. Is counting them acceptable?",
    "'On EPA watchlist' is our badge for the EPA's National Priority Sites list. Should we use the official name instead?",
    "Water, air and habitat points are set by hand, and the reason for each number is not recorded per entry (only the general rules on the method page). Should we record the basis for every score before launch?",
    "Older evidence: several entries cite cases from years ago, and some operators have since invested in fixes (the disclaimer mentions Moneypoint). Do we need a time limit, or more context next to old items?",
    "Map positions marked 'approx.' show a town or county. Could an approximate pin be read as an accusation about a specific site?",
    "The 'Why Sitka spruce matters' panel summarises research on the effects of conifer plantations. Is it framed fairly, given that Coillte is also a scored entry?",
    "Right of reply: is the corrections page (response times, publishing replies, interim removal while a dispute is reviewed) enough to support a 'fair and reasonable publication' defence? Should we notify every listed organisation before launch?",
    "The repository and the QA site are already public. Is there anything we should take down until the review is finished?",
    "We license the data under CC BY 4.0, so others can republish the scores. Does that create any risk if our scores are reused out of context?",
    "Private forest data: only totals per 5 km square are published, never plots or owners. Is any data-protection step needed?",
]


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.found = [], {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.stack and tag in ("td", "th", "b", "span", "br", "li", "p"):
            self.stack[-1][2].append(" ")
        key = None
        if tag == "h1":
            key = "Headline"
        elif "lede" in (a.get("class") or ""):
            key = "Introduction"
        elif "fact" == (a.get("class") or ""):
            key = "Headline fact"
        elif "disclaimer" in (a.get("class") or ""):
            key = "Disclaimer"
        elif "tiers" in (a.get("class") or ""):
            key = "Threat levels"
        elif tag == "tr":
            key = "Method table row"
        elif tag == "li" and self.stack and self.stack[-1][0] == "sitka":
            key = "Sitka panel point"
        if a.get("id") == "sitka-about":
            self.stack.append(("sitka", tag, []))
        elif key:
            self.stack.append((key, tag, []))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][1] == tag:
            key, _, buf = self.stack.pop()
            text = re.sub(r"\s+", " ", "".join(buf)).strip()
            if key != "sitka" and text:
                self.found.setdefault(key, []).append(text)
            if self.stack:
                self.stack[-1][2].append(" " + text + " ")

    def handle_data(self, data):
        if self.stack:
            self.stack[-1][2].append(data)


def basis_lines(p) -> list[str]:
    b = p.get("points_basis")
    if not b:
        return ["- **Reasons for hand-set points:** none recorded"]
    status = "reviewed, shown on the site" if b.get("reviewed") else "DRAFT: not yet reviewed, not shown on the site"
    return [f"- **Reasons for hand-set points ({status}):**",
            f"  - Water: {b.get('water')}", f"  - Air and odour: {b.get('air')}", f"  - Habitat: {b.get('habitat')}"]


def tier(v: float) -> str:
    return next(name for low, name in TIERS if v >= low)


def build():
    d = load_json(DATA_PATH)
    sources = {s["id"]: s for s in d["sources"]}
    ranked = sorted(d["polluters"], key=score, reverse=True)
    rows, md = [], []
    today = dt.date.today().isoformat()
    md += [f"# Threatshade claims register ({today})", "",
           "Prepared for pre-publication legal review. Generated by `scripts/claims_register.py` from `site/data/data.json` "
           "and `site/index.html`, so it matches what the site shows. Not committed to the public repository.", "",
           "For each organisation: the score and how it is made up, every badge and the rule that triggers it, and every "
           "piece of evidence with its source. The last sections list site-wide wording and open questions.", ""]
    md += ["## Questions for the reviewer", ""] + [f"{i}. {q}" for i, q in enumerate(QUESTIONS, 1)] + [""]
    md += ["## Organisations", ""]
    for rank, p in enumerate(ranked, 1):
        sc = score(p)
        pts = {"Climate": climate_pts(p.get("co2_tonnes")), "Water": p["points"]["water"], "Air and odour": p["points"]["air"],
               "Enforcement": enforce_pts(p["enforcement"]), "Habitat": p["points"]["habitat"]}
        badges = [(n, rule) for n, rule, test in BADGE_RULES if test(p)] + \
                 [(b["label"], "hand-set badge (extra_badges)") for b in p.get("extra_badges") or []]
        e = p["enforcement"]
        md += [f"### {rank}. {p['name']} ({p['sector']})", "",
               f"- **Score:** {sc:.0f}/100, tier **{tier(sc)}**",
               "- **Points:** " + ", ".join(f"{k} {v:.1f}" for k, v in pts.items()),
               f"- **Basis:** CO2 {p.get('co2_tonnes') or 'none'}"
               f"{' (estimated)' if p.get('co2_estimated') else ''}{' (' + str(p.get('co2_year')) + ')' if p.get('co2_year') else ''}; "
               f"priority list: {e.get('nps') or 'never'}; prosecutions counted: {e.get('prosecutions', 0)}; "
               f"stop orders: {e.get('stop_orders', 0)}; fine of EUR 100k+: {'yes' if e.get('big_fine') else 'no'}. "
               "Water, air and habitat points are set by hand; the reasons follow.",
               "- **Mapped sites:** " + "; ".join(s["name"] for s in p["sites"]),
               *basis_lines(p),
               "- **Badges shown:** " + ("; ".join(f"'{n}' ({r})" for n, r in badges) if badges else "none"), ""]
        if p.get("note"):
            md += [f"- **Note shown on the page:** {p['note']}", ""]
        md += ["| # | Date | Claim as shown on the site | Source |", "|---|---|---|---|"]
        for k, ev in enumerate(p["evidence"], 1):
            src = sources.get(ev["source"], {})
            md.append(f"| {k} | {ev['date']} | {ev['text'].replace('|', '/')} | [{src.get('id')}] {src.get('title', '?').replace('|', '/')} <{src.get('url', '')}> |")
            rows.append({"rank": rank, "organisation": p["name"], "sector": p["sector"], "score": round(sc), "tier": tier(sc),
                         "type": "evidence", "date": ev["date"], "claim": ev["text"], "rule_or_basis": "",
                         "source_id": src.get("id"), "source_title": src.get("title"), "source_url": src.get("url"),
                         "reviewer_ok": "", "reviewer_notes": ""})
        for n, r in badges:
            rows.append({"rank": rank, "organisation": p["name"], "sector": p["sector"], "score": round(sc), "tier": tier(sc),
                         "type": "badge", "date": "", "claim": n, "rule_or_basis": r, "source_id": "", "source_title": "",
                         "source_url": "", "reviewer_ok": "", "reviewer_notes": ""})
        for cat in ("water", "air", "habitat"):
            if p.get("points_basis"):
                rows.append({"rank": rank, "organisation": p["name"], "sector": p["sector"], "score": round(sc), "tier": tier(sc),
                             "type": f"points reason ({cat})", "date": "", "claim": p["points_basis"][cat],
                             "rule_or_basis": "reviewed" if p["points_basis"].get("reviewed") else "draft",
                             "source_id": "", "source_title": "", "source_url": "", "reviewer_ok": "", "reviewer_notes": ""})
        if p.get("note"):
            rows.append({"rank": rank, "organisation": p["name"], "sector": p["sector"], "score": round(sc), "tier": tier(sc),
                         "type": "note", "date": "", "claim": p["note"], "rule_or_basis": "", "source_id": "",
                         "source_title": "", "source_url": "", "reviewer_ok": "", "reviewer_notes": ""})
        md.append("")
    parser = _Text()
    parser.feed((ROOT / "site" / "index.html").read_text(encoding="utf-8"))
    md += ["## Site-wide wording", ""]
    for key in ("Headline", "Introduction", "Headline fact", "Method table row", "Threat levels", "Disclaimer", "Sitka panel point"):
        for text in parser.found.get(key, []):
            md.append(f"- **{key}:** {text}")
            rows.append({"rank": "", "organisation": "(site-wide)", "sector": "", "score": "", "tier": "", "type": key,
                         "date": "", "claim": text, "rule_or_basis": "", "source_id": "", "source_title": "",
                         "source_url": "", "reviewer_ok": "", "reviewer_notes": ""})
    md += ["", "## Badge rules", ""] + [f"- **{n}:** {r}" for n, r, _ in BADGE_RULES]
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "claims-register.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with open(OUT_DIR / "claims-register.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return len(ranked), len(rows)


if __name__ == "__main__":
    n, r = build()
    print(f"{n} organisations, {r} claims -> {OUT_DIR / 'claims-register.md'} and claims-register.csv")
