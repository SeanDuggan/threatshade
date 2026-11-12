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
        expected = {"uisce": 55, "coillte": 50, "northcork": 46, "aurivo": 43, "ryanair": 34, "bnm": 12}
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
        html = (ROOT / "site/index.html").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)", html))
        self.assertNotIn("style=", html)
        self.assertNotIn("<style", html)


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
        self.assertTrue(common.names_match("Tipperary Co-op Creamery", "Tipperary Co-operative Creamery Limited"))
        self.assertFalse(common.names_match("Kerry Ingredients", "Kerry Dairy Ireland"))
        self.assertFalse(common.names_match("ESB power stations", "Arrow Group"))

    def test_fetch_refuses_non_allowlisted_hosts(self):
        for url in ("https://evil.example/", "http://www.epa.ie/", "https://www.epa.ie.evil.com/"):
            with self.assertRaises(ValueError):
                fetch_updates.fetch(url, "text/html")

    def test_untrusted_text_from_list_is_caught_by_validator(self):
        d = data()
        d["polluters"][0]["name"] = fetch_updates.parse_nps(
            (ROOT / "tests/fixtures/nps_sample.html").read_text(encoding="utf-8"))["sites"][4]["licensee"] + " <x>"
        self.assertTrue(validate.validate(d).errors)


if __name__ == "__main__":
    unittest.main()
