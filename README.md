# Threatshade: Ireland's Polluter Scoreboard

A static web app that ranks Ireland's worst polluters on a map and a scoreboard, using public records: EU ETS carbon figures, the EPA's National Priority Sites list, EPA and DPP prosecutions, wastewater reports and habitat sensitivity. Every score links to its sources.

There is no server, database, login or form: just HTML, CSS, JavaScript and JSON, served by Cloudflare Pages. QA: https://threatshadeqa.pages.dev.

## Layout

```
site/                  Everything that is deployed (Cloudflare Pages output directory)
  index.html, 404.html, privacy.html, corrections.html
  app.js, styles.css   Scoring, map and scoreboard; data is rendered with DOM APIs only
  data/                data.json (polluters, evidence, sources), ireland-map.json, sitka-grid.json, native-grid.json
  assets/              Logo, team avatars, self-hosted fonts (OFL)
  _headers             Security headers (CSP, HSTS and others)
  .well-known/security.txt, security-policy.txt
  favicon.*, icon-*.png, site.webmanifest
scripts/               Python, standard library only: fetch_updates, validate, build_map, build_tree_layers, claims_register
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
- **Tree layers** (both off by default): hectares of Sitka spruce, and of native species (oak, birch, alder, ash, Scots pine, hazel, holly, yew, rowan, willow, elm, hawthorn), per ~5 km square, from the Coillte Forest Inventory and the DAFM Private Forest Estate 2023 (both CC BY 4.0). Each plot counts its area times that species' share, stocked forest only. Broadleaf mixes with unrecorded species are left out of the native layer. Only 5 km totals are published, never plot shapes or owners. To refresh both, download the DAFM zip from [data.gov.ie](https://data.gov.ie/dataset/dafm-private-forest-estate-2023) (its server blocks scripts) and run `python3 scripts/build_tree_layers.py --private path/to/privateforests2023.zip`.

## Security

See `SECURITY.md` and `docs/THREAT_MODEL.md`. Reports go to security@threatshade.com. The `security.txt` expiry (2027-11-01) must be renewed before then.

The repository is public. `main` is protected: changes go through a pull request with one approving review from the code owner of the files changed (see `.github/CODEOWNERS`), the `test` check must pass, open review conversations must be resolved, and force pushes and branch deletion are blocked. Also on: secret scanning with push protection, Dependabot alerts and security updates, a read-only default workflow token.

## Deploy

Cloudflare Pages builds from `main` with no build command and output directory `site`, so only `site/` is published (a test fails if any Markdown file lands there). Check the headers after a deploy with `curl -sI https://threatshadeqa.pages.dev/`.

## Legal review and corrections

`python3 scripts/claims_register.py` writes `reports/claims-register.md` and `.csv`: every organisation's score, badges (with the rule behind each), evidence and sources, the site-wide wording, and open questions for the reviewer. `reports/` is git-ignored, so the register stays off the public repository.

Corrections and replies from listed organisations go to info@threatshade.com and are handled as described on `site/corrections.html`; every change is added to the log on that page. Security reports go to security@threatshade.com.

## Before going public

- Legal review of every claim, badge and the method wording; keep the QA site (threatshadeqa.pages.dev) behind Cloudflare Access until then.

## Licence

Code: MIT (`LICENSE`). Data and written content: CC BY 4.0 (`LICENSE-DATA.md`). The Threatshade name and logo are not covered, and third-party data keeps its own licence.
