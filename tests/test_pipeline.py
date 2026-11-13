import copy
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import common
import fetch_updates
import validate


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


import build_map


class CountyMap(unittest.TestCase):
    def setUp(self):
        self.m = common.load_json(common.MAP_PATH)

    def test_map_file_is_valid(self):
        self.assertEqual(validate.validate_map(self.m).errors, [])
        self.assertEqual(len(self.m["areas"]), 27)

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
        self.assertAlmostEqual(pts[0][0], 480.0)

    def test_build_map_refuses_unsafe_svg(self):
        with self.assertRaises(ValueError):
            build_map.build('<!DOCTYPE svg [<!ENTITY a "x">]><svg xmlns="http://www.w3.org/2000/svg"/>')
        with self.assertRaises(ValueError):
            build_map.parse_path("M 0,0 C 1,1 2,2 3,3 Z")


import build_tree_layers as build_sitka


class SitkaGrid(unittest.TestCase):
    def sample(self):
        return build_sitka.grid([(53.01, -8.01, 10.0), (53.02, -8.02, 5.5), (49.0, -8.0, 99.0)], [(54.5, -7.0, 2.4)])

    def test_grid_adds_up_both_sources(self):
        g = self.sample()
        self.assertEqual(len(g["cells"]), 2)
        self.assertEqual(g["total_ha"], 16 + 2)
        self.assertEqual((g["coillte_ha"], g["private_ha"]), (16, 2))
        self.assertEqual(validate.validate_tree_grid(g).errors, [])

    def test_validator_rejects_bad_cells(self):
        for bad in ([1, 2], [1, 2, 0], [1, 2, 99999], [-1, 2, 5], [1, 2, "5"], [1, 2, True]):
            g = self.sample()
            g["cells"].append(bad)
            self.assertTrue(validate.validate_tree_grid(g).errors, bad)

    def test_validator_rejects_wrong_totals_unknown_keys_and_bad_sources(self):
        g = self.sample(); g["total_ha"] += 1
        self.assertTrue(validate.validate_tree_grid(g).errors)
        g = self.sample(); g["private_ha"] += 500
        self.assertTrue(validate.validate_tree_grid(g).errors)
        g = self.sample(); g["script"] = "x"
        self.assertTrue(validate.validate_tree_grid(g).errors)
        g = self.sample(); g["sources"][0]["url"] = "https://evil.example/"
        self.assertTrue(validate.validate_tree_grid(g).errors)

    def test_published_grid_is_valid(self):
        g = common.load_json(common.SITKA_PATH)
        self.assertEqual(validate.validate_tree_grid(g).errors, [])
        self.assertGreater(g["coillte_ha"], 100_000)
        self.assertGreater(g["private_ha"], 100_000)
        n = common.load_json(common.NATIVE_PATH)
        self.assertEqual(validate.validate_tree_grid(n, label="native").errors, [])
        self.assertEqual(n["species"], "Native Irish trees")

    def test_itm_conversion_matches_known_point(self):
        lat, lng = build_sitka.itm_to_latlng(715830, 734697)
        self.assertAlmostEqual(lat, 53.3498, places=3)
        self.assertAlmostEqual(lng, -6.2603, places=3)

    def test_only_the_sitka_share_counts(self):
        self.assertAlmostEqual(build_sitka.share([("SS", 60), ("NS", 40)], {"SS"}), 0.6)
        self.assertEqual(build_sitka.share([("BMO", 100)], {"SS"}), 0)
        native = build_sitka.LAYERS["native"]["codes"]
        self.assertAlmostEqual(build_sitka.share([("OAK", 50), ("BI", 20), ("SS", 30)], native), 0.7)
        self.assertAlmostEqual(build_sitka.share([("SP", 60), ("LPS", 40)], native), 0.6)
        self.assertEqual(build_sitka.share([("BMO", 60), ("BE", 40)], native), 0)

    def test_reads_private_shapefile_from_zip(self):
        import io, struct, tempfile, zipfile

        def shp(boxes):
            recs = b""
            for k, (x0, y0, x1, y1) in enumerate(boxes, 1):
                body = struct.pack("<i4d", 15, x0, y0, x1, y1) + b"\0" * 8
                recs += struct.pack(">II", k, len(body) // 2) + body
            head = struct.pack(">I", 9994) + b"\0" * 20 + struct.pack(">I", (100 + len(recs)) // 2)
            return head + struct.pack("<ii", 1000, 15) + b"\0" * 64 + recs

        def dbf(rows):
            fields = [("Sp_1", 10), ("SpPerc_1", 10), ("Sp_2", 10), ("SpPerc_2", 10), ("LUC", 10), ("Area_ha", 10)]
            rl = 1 + sum(l for _, l in fields)
            hl = 32 + 32 * len(fields) + 1
            out = bytearray(b"\x03" + b"\0" * 3 + struct.pack("<IHH", len(rows), hl, rl) + b"\0" * 20)
            for nm, l in fields:
                out += nm.encode().ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([l]) + b"\0" * 15
            out += b"\x0d"
            for r in rows:
                out += b" " + b"".join(str(r.get(nm, "")).encode().ljust(l)[:l] for nm, l in fields)
            return bytes(out)

        rows = [{"Sp_1": "SS", "SpPerc_1": 60, "Sp_2": "NS", "SpPerc_2": 40, "LUC": "CHF", "Area_ha": 10},
                {"Sp_1": "SS", "SpPerc_1": 100, "LUC": "Road", "Area_ha": 5},
                {"Sp_1": "ASH", "SpPerc_1": 100, "LUC": "BHF", "Area_ha": 7}]
        boxes = [(715800, 734600, 715900, 734800)] * 3
        tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False); tmp.close()
        with zipfile.ZipFile(tmp.name, "w") as z:
            z.writestr(build_sitka.PRIVATE_STEM + ".shp", shp(boxes))
            z.writestr(build_sitka.PRIVATE_STEM + ".dbf", dbf(rows))
        old = build_sitka.MIN_PLOTS
        try:
            build_sitka.MIN_PLOTS = 1
            layers = build_sitka.read_private(tmp.name)
        finally:
            build_sitka.MIN_PLOTS = old
            Path(tmp.name).unlink()
        self.assertEqual(len(layers["sitka"]), 1)
        lat, lng, ha = layers["sitka"][0]
        self.assertAlmostEqual(ha, 6.0)
        self.assertEqual([round(p[2], 3) for p in layers["native"]], [7.0])
        self.assertAlmostEqual(lat, 53.35, places=2)

    def test_build_only_contacts_allowlisted_host(self):
        self.assertTrue(common.host_allowed(build_sitka.LAYER, common.allowlist()["layer_fetch_hosts"]))
        self.assertFalse(common.host_allowed(build_sitka.LAYER, common.allowlist()["fetch_hosts"]))

    def test_page_only_hosts_are_not_allowed_as_sources(self):
        cfg = common.allowlist()
        self.assertFalse(set(cfg["page_link_hosts"]) & set(cfg["link_hosts"]))
        d = data()
        d["sources"][0]["url"] = "https://gist.github.com/someone/abc"
        self.assertTrue(validate.validate(d).errors)


class PageLinks(unittest.TestCase):
    def test_external_links_in_pages_are_https_and_allowlisted(self):
        cfg = common.allowlist()
        hosts = cfg["link_hosts"] + cfg["page_link_hosts"]
        for page in sorted((ROOT / "site").rglob("*.html")):
            html = page.read_text(encoding="utf-8")
            for url in re.findall(r'href="(https?://[^"]+)"', html):
                self.assertTrue(common.host_allowed(url.replace("&amp;", "&"), hosts), f"{page.name}: {url}")
            for tag in re.findall(r'<a [^>]*href="https?://[^>]*>', html):
                self.assertIn('rel="noopener noreferrer"', tag, page.name)


class PointsBasis(unittest.TestCase):
    def test_every_polluter_has_reasons_for_hand_set_points(self):
        for p in data()["polluters"]:
            b = p.get("points_basis")
            self.assertIsInstance(b, dict, p["id"])
            for k in ("water", "air", "habitat"):
                self.assertTrue(b.get(k), f"{p['id']}.{k}")

    def test_validator_rejects_bad_reasons(self):
        for bad in ({"water": "x", "air": "x", "habitat": "x", "reviewed": "yes"},
                    {"water": "<b>x</b>", "air": "x", "habitat": "x", "reviewed": False},
                    {"water": "x", "air": "x", "habitat": "x", "reviewed": False, "extra": 1}):
            d = data()
            d["polluters"][0]["points_basis"] = bad
            self.assertTrue(validate.validate(d).errors, bad)

    def test_page_only_shows_reviewed_reasons(self):
        js = (ROOT / "site/app.js").read_text(encoding="utf-8")
        self.assertIn("basis.reviewed === true", js)


class ForestSummary(unittest.TestCase):
    def sample(self):
        return build_sitka.summarise({"stocked": 100.4, "native": 10, "non_native": 70, "sitka": 50},
                                     {"stocked": 50, "native": 5, "non_native": 30, "sitka": 20})

    def test_summary_adds_up(self):
        s = self.sample()
        self.assertEqual(s["total"], {"stocked": 150, "native": 15, "non_native": 100, "sitka": 70, "unspecified": 35})
        self.assertEqual(validate.validate_forest_summary(s).errors, [])

    def test_validator_rejects_inconsistent_summary(self):
        s = self.sample(); s["total"]["native"] += 1
        self.assertTrue(validate.validate_forest_summary(s).errors)
        s = self.sample(); s["coillte"]["sitka"] = s["coillte"]["non_native"] + 1
        self.assertTrue(validate.validate_forest_summary(s).errors)
        s = self.sample(); s["sources"][0]["url"] = "https://evil.example/"
        self.assertTrue(validate.validate_forest_summary(s).errors)

    def test_native_and_non_native_lists_do_not_overlap(self):
        self.assertFalse(build_sitka.NATIVE & build_sitka.NON_NATIVE)
        self.assertIn("SS", build_sitka.NON_NATIVE)
        self.assertIn("SP", build_sitka.NATIVE)

    def test_published_summary_is_valid(self):
        s = common.load_json(common.SUMMARY_PATH)
        self.assertEqual(validate.validate_forest_summary(s).errors, [])

