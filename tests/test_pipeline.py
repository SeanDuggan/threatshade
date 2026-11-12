"""Run with: python3 -m unittest discover -s tests -v"""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common  # noqa: E402
import fetch_updates  # noqa: E402
import validate  # noqa: E402


def data():
    return json.loads((ROOT / "site/data/data.json").read_text(encoding="utf-8"))


def by_id(d, pid):
    return next(p for p in d["polluters"] if p["id"] == pid)


class DataFile(unittest.TestCase):
    def test_current_data_is_valid(self):
        r = validate.validate(data())
        self.assertEqual(r.errors, [])

    def test_scores_match_published_page(self):
        d = data()
        expected = {"uisce": 55, "coillte": 50, "northcork": 49, "aurivo": 43, "ryanair": 34, "bnm": 12}
        for pid, want in expected.items():
            self.assertEqual(round(common.score(by_id(d, pid))), want, pid)

    def test_allowlist_in_sync_with_frontend(self):
        js = (ROOT / "site/app.js").read_text(encoding="utf-8")
        block = re.search(r"ALLOWED_LINK_HOSTS = \[(.*?)\]", js, re.S).group(1)
        front = set(re.findall(r'"([^"]+)"', block))
        self.assertEqual(front, set(common.allowlist()["link_hosts"]))

    def test_frontend_never_uses_innerhtml(self):
        js = (ROOT / "site/app.js").read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
        for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(bad, code)

    def test_html_has_no_inline_script_or_style(self):
        pages = sorted((ROOT / "site").rglob("*.html"))
        self.assertIn(ROOT / "site/404.html", pages)
        for page in pages:
            html = page.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)", html), page.name)
            self.assertNotIn("style=", html, page.name)
            self.assertNotIn("<style", html, page.name)

    def test_no_third_party_hosts_in_page_or_csp(self):
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r'<(link|script)[^>]+(href|src)="https?://', html))
        csp = next(l for l in (ROOT / "site/_headers").read_text(encoding="utf-8").splitlines()
                   if "Content-Security-Policy" in l)
        self.assertNotIn("https://", csp)

    def test_no_markdown_in_published_site(self):
        # site/ is the Cloudflare Pages output directory; repo docs must never be published.
        found = [str(p.relative_to(ROOT)) for p in (ROOT / "site").rglob("*")
                 if p.is_file() and p.suffix.lower() in (".md", ".markdown", ".mdx")]
        self.assertEqual(found, [], "Markdown files must not be in site/")


class Validator(unittest.TestCase):
    def errs(self, mutate):
        d = data()
        mutate(d)
        return validate.validate(d).errors

    def test_rejects_markup_in_name(self):
        e = self.errs(lambda d: d["polluters"][0].update(name='<img src=x onerror=alert(1)>'))
        self.assertTrue(any("name" in x for x in e))

    def test_rejects_javascript_and_offlist_urls(self):
        for bad in ("javascript:alert(1)", "http://www.epa.ie/x", "https://epa.ie.evil.com/x",
                    "https://user:pw@www.epa.ie/", "https://evil.example/"):
            e = self.errs(lambda d, b=bad: d["sources"][0].update(url=b))
            self.assertTrue(any("url" in x for x in e), bad)

    def test_rejects_out_of_range_points(self):
        self.assertTrue(self.errs(lambda d: d["polluters"][0]["points"].update(water=99)))
        self.assertTrue(self.errs(lambda d: d["polluters"][0]["points"].update(air=True)))

    def test_rejects_unknown_source_reference(self):
        self.assertTrue(self.errs(lambda d: d["polluters"][0]["evidence"][0].update(source=9999)))

    def test_rejects_site_outside_ireland(self):
        self.assertTrue(self.errs(lambda d: d["polluters"][0]["sites"][0].update(lat=48.85, lng=2.35)))

    def test_compare_flags_big_swings_and_new_entries(self):
        old, new = data(), data()
        by_id(new, "ryanair")["points"]["water"] = 25
        added = copy.deepcopy(by_id(new, "arrow")); added["id"] = "newco"; added["name"] = "New Co"
        new["polluters"].append(added)
        r = validate.compare(old, new, validate.Result())
        text = "\n".join(r.warnings)
        self.assertIn("LARGE SCORE CHANGE: Ryanair", text)
        self.assertIn("ADDED polluter: New Co", text)


class Fetching(unittest.TestCase):
    def test_parse_priority_list_fixture(self):
        html = (ROOT / "tests/fixtures/nps_sample.html").read_text(encoding="utf-8")
        nps = fetch_updates.parse_nps(html)
        self.assertEqual(nps["quarter"], "Q2 2026")
        self.assertEqual(len(nps["sites"]), 5)
        self.assertEqual(nps["sites"][1]["licensee"], "Arrow Group")

    def test_name_matching(self):
        self.assertTrue(common.names_match("North Cork Co-Op Creameries", "North Cork Co-Op Creameries Limited"))
        self.assertTrue(common.names_match("Kingspan (Kingscourt)", "Kingspan Building Products"))

    def test_only_exact_unqualified_names_change_status(self):
        self.assertEqual(common.match_kind("North Cork Co-Op Creameries", "North Cork Co-Op Creameries Limited"), "exact")
        # A different site of the same company must not be applied automatically.
        self.assertEqual(common.match_kind("Kingspan (Kingscourt)", "Kingspan Insulation Ltd"), "possible")
        self.assertEqual(common.match_kind("Kingspan (Kingscourt)", "Kingspan Limited"), "possible")
        self.assertEqual(common.match_kind("Kerry Ingredients", "Kerry Ingredients Listowel"), "possible")
        self.assertIsNone(common.match_kind("ESB power stations", "Arrow Group"))

    def test_possible_match_does_not_change_published_status(self):
        d = data()
        k = by_id(d, "kingspan"); k["enforcement"]["nps"] = None
        listing = {"quarter": "Q2 2026", "sites": [
            {"licensee": "Kingspan Insulation Limited", "county": "Meath", "sector": "x", "issue": "y"}]}
        orig = fetch_updates.parse_nps, fetch_updates.fetch, fetch_updates.write_json
        try:
            fetch_updates.parse_nps = lambda html: listing
            fetch_updates.fetch = lambda url, accept: b""
            fetch_updates.write_json = lambda path, obj: None
            fetch_updates.report.clear()
            fetch_updates.step_priority_sites(d)
        finally:
            fetch_updates.parse_nps, fetch_updates.fetch, fetch_updates.write_json = orig
        self.assertIsNone(k["enforcement"]["nps"])
        self.assertTrue(any("POSSIBLE MATCH" in line for line in fetch_updates.report))
        self.assertTrue(common.names_match("Tipperary Co-op Creamery", "Tipperary Co-operative Creamery Limited"))
        self.assertFalse(common.names_match("Kerry Ingredients", "Kerry Dairy Ireland"))
        self.assertFalse(common.names_match("ESB power stations", "Arrow Group"))

    def test_fetch_refuses_non_allowlisted_hosts(self):
        for url in ("https://evil.example/", "http://www.epa.ie/", "https://www.epa.ie.evil.com/"):
            with self.assertRaises(ValueError):
                fetch_updates.fetch(url, "text/html")

    def test_report_shows_fetched_text_literally(self):
        evil = "Acme [click here](https://evil.example) ![x](https://evil.example/p.png) @someone `x`\n# heading"
        out = fetch_updates.md_text(evil)
        self.assertTrue(out.startswith("`") and out.endswith("`"))
        self.assertEqual(out.count("`"), 2)
        self.assertNotIn("\n", out)
        self.assertEqual(fetch_updates.md_url("https://www.epa.ie/a/prosecutions-2026/epa-prosecutes-x/"),
                         "<https://www.epa.ie/a/prosecutions-2026/epa-prosecutes-x/>")
        self.assertTrue(fetch_updates.md_url("https://www.epa.ie/x>[y](https://evil.example)").startswith("`"))

    def test_baseline_ref_rejects_option_like_values(self):
        with self.assertRaises(SystemExit):
            validate.load_baseline(type("A", (), {"baseline": None, "baseline_ref": "--output=/tmp/x"})())

    def test_untrusted_text_from_list_is_caught_by_validator(self):
        d = data()
        d["polluters"][0]["name"] = fetch_updates.parse_nps(
            (ROOT / "tests/fixtures/nps_sample.html").read_text(encoding="utf-8"))["sites"][4]["licensee"] + " <x>"
        self.assertTrue(validate.validate(d).errors)


if __name__ == "__main__":
    unittest.main()


import build_map  # noqa: E402


class CountyMap(unittest.TestCase):
    def setUp(self):
        self.m = common.load_json(common.MAP_PATH)

    def test_map_file_is_valid(self):
        self.assertEqual(validate.validate_map(self.m).errors, [])
        self.assertEqual(len(self.m["areas"]), 27)  # 26 counties + Northern Ireland

    def test_known_towns_land_in_the_right_county(self):
        towns = [("Dublin", 53.3498, -6.2603, "Dublin"), ("Cork", 51.8985, -8.4756, "Cork"),
                 ("Galway", 53.2707, -9.0568, "Galway"), ("Glin", 52.5714, -9.2836, "Limerick"),
                 ("Tarbert", 52.5728, -9.3753, "Kerry"), ("Kingscourt", 53.9065, -6.8037, "Cavan"),
                 ("Letterkenny", 54.9558, -7.7342, "Donegal"), ("Waterford", 52.2593, -7.1101, "Waterford")]
        for name, lat, lng, county in towns:
            a = common.area_at(self.m, lat, lng)
            self.assertIsNotNone(a, name)
            self.assertEqual(a["name"], county, name)

    def test_every_polluter_site_is_on_land(self):
        for p in data()["polluters"]:
            for s in p["sites"]:
                self.assertIsNotNone(common.area_at(self.m, s["lat"], s["lng"]), s["name"])

    def test_map_rejects_markup_and_bad_rings(self):
        bad = copy.deepcopy(self.m)
        bad["areas"][0]["rings"][0] = "1,2,3,4,5,6,7,8<script>"
        self.assertTrue(validate.validate_map(bad).errors)
        bad = copy.deepcopy(self.m)
        bad["areas"][0]["name"] = "<img src=x>"
        self.assertTrue(validate.validate_map(bad).errors)
        bad = copy.deepcopy(self.m)
        bad["areas"][0]["onload"] = "x"
        self.assertTrue(validate.validate_map(bad).errors)

    def test_build_map_from_svg(self):
        out = build_map.build((ROOT / "tests/fixtures/mini_map.svg").read_text(encoding="utf-8"))
        self.assertEqual([a["id"] for a in out["areas"]], ["IE-CW"])
        self.assertEqual(len(out["areas"][0]["rings"]), 2)
        pts = common.decode_ring(out["areas"][0]["rings"][1], out["unit"])
        self.assertAlmostEqual(pts[0][0], 480.0)  # relative move after close is from the subpath start

    def test_build_map_refuses_unsafe_svg(self):
        with self.assertRaises(ValueError):
            build_map.build('<!DOCTYPE svg [<!ENTITY a "x">]><svg xmlns="http://www.w3.org/2000/svg"/>')
        with self.assertRaises(ValueError):
            build_map.parse_path("M 0,0 C 1,1 2,2 3,3 Z")
