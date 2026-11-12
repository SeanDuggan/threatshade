#!/usr/bin/env python3
"""Weekly data refresh. Standard library only, so there are no third-party packages to compromise.

What it does:
  1. EPA National Priority Sites list -> updates enforcement.nps for polluters already on the board,
     and reports listed sites that are not on the board (a human decides whether to add them).
  2. EPA prosecutions index for this year and last -> reports prosecutions not seen before.
     Never changes scores by itself: a human reads the case and edits data.json.
  3. EPA LEAP open-data API -> records compliance-record counts for known licences and reports changes.

Everything fetched is treated as untrusted: only allowlisted https hosts, size and time limits,
no redirects off the allowlist, strict parsing, and sanity bounds. If a source looks wrong
(for example a page redesign returns zero rows) the step is skipped and reported, never applied.

Writes: site/data/data.json (only the nps field), data/state/*.json, reports/update-report.md
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from common import DATA_PATH, REPORT_PATH, STATE_DIR, allowlist, host_allowed, load_json, names_match, write_json  # noqa: E402

NPS_URL = "https://www.epa.ie/our-services/compliance--enforcement/whats-happening/national-priority-sites-list"
PROS_URL = "https://www.epa.ie/our-services/compliance--enforcement/whats-happening/prosecutions-and-penalties/prosecutions-{year}/"
LEAP_PROFILE = "https://data.epa.ie/leap/api/v1/LicenceProfile/byregno?licence_reg_no={reg}"
LEAP_COMPLIANCE = "https://data.epa.ie/leap/api/v1/ComplianceList/compliancelist?licence_profile_id={pid}&page=1&per_page=50"

USER_AGENT = "ThreatshadeDataBot/1.0 (+https://www.threatshade.com; weekly public-data refresh)"
MAX_BYTES = 3_000_000
TIMEOUT = 25
PAUSE = 1.5  # seconds between requests, to be polite
UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")

FETCH_HOSTS = allowlist()["fetch_hosts"]
report: list[str] = []


def say(line: str = "") -> None:
    print(line)
    report.append(line)


class _AllowlistRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_allowed(newurl, FETCH_HOSTS):
            raise urllib.error.HTTPError(newurl, code, "redirect to non-allowlisted host blocked", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_AllowlistRedirects())


def fetch(url: str, accept: str) -> bytes:
    if not host_allowed(url, FETCH_HOSTS):
        raise ValueError(f"host not allowlisted: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    time.sleep(PAUSE)
    with _opener.open(req, timeout=TIMEOUT) as resp:
        body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError(f"response too large: {url}")
    return body


# ---------------------------------------------------------------- 1. priority sites
class _TableParser(HTMLParser):
    """Collects table rows as lists of cell text, plus all heading text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self._row, self._cell, self.headings, self._in_h = [], None, None, [], False

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in ("h1", "h2", "h3"):
            self._in_h, self._h = True, []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None
        elif tag in ("h1", "h2", "h3") and self._in_h:
            self.headings.append(re.sub(r"\s+", " ", "".join(self._h)).strip())
            self._in_h = False

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        if self._in_h:
            self._h.append(data)


def parse_nps(html: str) -> dict:
    p = _TableParser()
    p.feed(html)
    quarter = next((m.group(1) for h in p.headings for m in [re.search(r"(Q[1-4]\s+20\d\d)", h)] if m), None)
    sites = []
    for row in p.rows:
        if len(row) < 2 or row[0].lower() in ("licensee", "name", "site"):
            continue
        name = row[0][:150]
        if not re.search(r"[A-Za-z]", name):
            continue
        sites.append({"licensee": name, "county": row[1][:60] if len(row) > 1 else "",
                      "sector": row[2][:80] if len(row) > 2 else "", "issue": row[3][:200] if len(row) > 3 else ""})
    return {"quarter": quarter, "sites": sites}


def step_priority_sites(data: dict) -> bool:
    say("### EPA National Priority Sites")
    try:
        nps = parse_nps(fetch(NPS_URL, "text/html").decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001 - report and skip, never crash the whole run
        say(f"- SKIPPED: could not fetch or parse the list ({type(e).__name__}: {e})")
        return False
    n = len(nps["sites"])
    if not (1 <= n <= 40):
        say(f"- SKIPPED: parsed {n} sites, outside the expected 1 to 40. The page layout may have changed; check by hand.")
        return False
    write_json(STATE_DIR / "nps_latest.json", {"fetched": dt.date.today().isoformat(), **nps})
    say(f"- List found: {nps['quarter'] or 'quarter not detected'}, {n} sites.")

    changed = False
    listed = [s["licensee"] for s in nps["sites"]]
    for p in data["polluters"]:
        on_list = any(names_match(p["name"], l) for l in listed)
        cur = p["enforcement"].get("nps")
        new = "current" if on_list else ("past" if cur == "current" else cur)
        if new != cur:
            say(f"- CHANGED: {p['name']} priority status {cur} -> {new}")
            p["enforcement"]["nps"] = new
            changed = True
    for s in nps["sites"]:
        if not any(names_match(p["name"], s["licensee"]) for p in data["polluters"]):
            say(f"- NEW ON LIST, not on scoreboard: {s['licensee']} ({s['county']}, {s['sector']}): {s['issue']}. Add by hand with sources if appropriate.")
    if not changed:
        say("- No status changes for polluters already on the board.")
    return changed


# ---------------------------------------------------------------- 2. prosecutions
class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self._href, self._text = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._text = dict(attrs).get("href"), []

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, re.sub(r"\s+", " ", "".join(self._text)).strip()))
            self._href = None

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)


def step_prosecutions() -> None:
    say("")
    say("### EPA prosecutions")
    seen_path = STATE_DIR / "seen_prosecutions.json"
    seen = load_json(seen_path) if seen_path.exists() else {"urls": []}
    known = set(seen["urls"])
    first_run = not known
    year = dt.date.today().year
    new = []
    for y in (year - 1, year):
        url = PROS_URL.format(year=y)
        try:
            lp = _LinkParser()
            lp.feed(fetch(url, "text/html").decode("utf-8", "replace"))
        except Exception as e:  # noqa: BLE001
            say(f"- SKIPPED {y}: {type(e).__name__}: {e}")
            continue
        for href, text in lp.links:
            full = urllib.parse.urljoin(url, href)
            if not host_allowed(full, ["epa.ie"]) or f"prosecutions-{y}/" not in full or not re.search(r"prosecutes", full):
                continue
            if full not in known:
                known.add(full)
                new.append((text[:200] or full, full))
    if len(new) > 200:
        say(f"- SKIPPED: {len(new)} new links is implausible; check the page by hand.")
        return
    seen["urls"] = sorted(known)
    write_json(seen_path, seen)
    if first_run:
        say(f"- First run: recorded {len(new)} existing prosecutions as the baseline.")
    elif new:
        for text, url in new:
            say(f"- NEW: {text} <{url}>. Read it, then update the polluter's evidence and prosecutions count by hand.")
    else:
        say("- No new prosecutions.")


# ---------------------------------------------------------------- 3. LEAP API
def _first_list(obj):
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list):
                return v
    return None


def _find_profile_id(obj):
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(v, str) and "profile" in k.lower() and k.lower().endswith("id") and UUID_RE.match(v):
                    return v
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def step_leap(data: dict) -> None:
    say("")
    say("### EPA LEAP compliance records")
    state_path = STATE_DIR / "leap_counts.json"
    prev = load_json(state_path) if state_path.exists() else {}
    now, changes = {}, 0
    for p in data["polluters"]:
        for reg in p.get("epa_licences") or []:
            if not re.match(r"^[A-Z]\d{4}-\d{2}$", reg):
                continue
            try:
                prof = json.loads(fetch(LEAP_PROFILE.format(reg=urllib.parse.quote(reg)), "application/json"))
                pid = _find_profile_id(prof)
                if not pid:
                    say(f"- {reg} ({p['name']}): no profile id found in API response; skipped.")
                    continue
                comp = json.loads(fetch(LEAP_COMPLIANCE.format(pid=pid), "application/json"))
                items = _first_list(comp)
                if items is None:
                    say(f"- {reg} ({p['name']}): unexpected response shape; skipped.")
                    continue
                count = len(items)
            except Exception as e:  # noqa: BLE001
                say(f"- {reg} ({p['name']}): SKIPPED ({type(e).__name__})")
                continue
            now[reg] = count
            before = prev.get(reg)
            if before is not None and count != before:
                changes += 1
                say(f"- CHANGED: {reg} ({p['name']}) compliance records on first page {before} -> {count}. Review on LEAP.")
    write_json(state_path, {**prev, **now})
    if not changes:
        say(f"- Checked {len(now)} licences; no changes detected.")


def main() -> int:
    data = load_json(DATA_PATH)
    say(f"# Weekly data check, {dt.date.today().isoformat()}")
    say("")
    say("Automated changes are limited to the priority-site status field. Everything else below needs a human decision.")
    say("")
    changed = step_priority_sites(data)
    step_prosecutions()
    step_leap(data)
    if changed:
        write_json(DATA_PATH, data)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(report) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
