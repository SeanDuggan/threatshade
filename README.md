# Threatshade: Ireland's Polluter Scoreboard

A static web app that ranks Ireland's worst polluters on a map and a scoreboard, using public records: EU ETS carbon figures, the EPA's National Priority Sites list, EPA and DPP prosecutions, wastewater reports and habitat sensitivity. Every score links to its sources.

There is no server, database, login or form: just HTML, CSS, JavaScript and JSON, served by Cloudflare Pages. QA: https://threatshadeqa.pages.dev (qa.threatshade.com to follow).

## Layout

```
site/                  Everything that is deployed (Cloudflare Pages output directory)
  index.html, 404.html, privacy.html
  app.js, styles.css   Scoring, map and scoreboard; data is rendered with DOM APIs only
  data/                data.json (polluters, evidence, sources), ireland-map.json, sitka-grid.json
  assets/              Logo, team avatars, self-hosted fonts (OFL)
  _headers             Security headers (CSP, HSTS and others)
  .well-known/security.txt, security-policy.txt
  favicon.*, icon-*.png, site.webmanifest
scripts/               Python, standard library only: fetch_updates, validate, build_map, build_sitka
config/                link_allowlist.json: hosts that links and fetchers may use
data/state/            What the weekly fetcher saw last time
tests/                 python3 -m unittest discover -s tests
docs/                  Threat model and research notes
```

## Run it locally

```bash
python3 -m http.server 8000 --directory site
python3 -m unittest discover -s tests
python3 scripts/validate.py
```

Then open http://localhost:8000 (`fetch()` does not work from `file://`). Python 3.10+, nothing to install.

## Data

- **Scoreboard:** edit `site/data/data.json` by hand, update `last_reviewed`, run the tests and validator, and open a pull request. Every claim needs a source on an allowlisted host.
- **Weekly update:** every Monday a workflow checks the EPA priority sites list, prosecutions pages and LEAP API. It only changes priority-list status by itself, and only on an exact name match; everything else goes into a report. If anything changed it opens a pull request for review.
- **County map:** from MapSVG's Ireland map (CC0), converted to integer outlines by `build_map.py`; no SVG markup reaches the page. To refresh: download `https://mapsvg.com/maps/geo-calibrated/ireland.svg` and run `python3 scripts/build_map.py ireland.svg`.
- **Sitka spruce overlay** (off by default): hectares of Sitka per ~5 km square, from the Coillte Forest Inventory and the DAFM Private Forest Estate 2023 (both CC BY 4.0). Each plot counts its area times Sitka's share, stocked forest only. Only 5 km totals are published, never plot shapes or owners. To refresh, download the DAFM zip from [data.gov.ie](https://data.gov.ie/dataset/dafm-private-forest-estate-2023) (its server blocks scripts) and run `python3 scripts/build_sitka.py --private path/to/privateforests2023.zip`.

## Security

See `SECURITY.md` and `docs/THREAT_MODEL.md`. Reports go to security@threatshade.com. The `security.txt` expiry (2027-11-01) must be renewed before then.

Repository settings in place: read-only default workflow token, Actions allowed to open pull requests, Dependabot alerts and security updates, CODEOWNERS. Branch protection and secret scanning need the repository to be public (or GitHub Pro), so turn them on at launch.

## Deploy

Cloudflare Pages builds from `main` with no build command and output directory `site`, so only `site/` is published (a test fails if any Markdown file lands there). Check the headers after a deploy with `curl -sI https://threatshadeqa.pages.dev/`.

## Before going public

- Legal review of every claim, badge and the method wording; keep QA behind Cloudflare Access until then.
- A corrections and right-of-reply page.
- Turn on branch protection and secret scanning once the repository is public.
- Add a licence for the code and data if others should reuse them.
