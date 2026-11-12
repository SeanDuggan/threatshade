# Threatshade: Ireland's Polluter Scoreboard

A static web app that ranks Ireland's worst polluters on a map and a scoreboard, using public records: EU ETS carbon figures, the EPA's National Priority Sites list, EPA and DPP prosecutions, wastewater reports and habitat sensitivity. Every score is linked to its sources.

The site has no server, database, login or forms. It is plain HTML, CSS and JavaScript plus one JSON data file, so it can be served from Cloudflare Pages.

## Repository layout

```
site/                    What gets deployed (Cloudflare Pages output directory)
  index.html             Page markup; no inline scripts or styles
  styles.css             All styling
  app.js                 Scoring, map and scoreboard; renders data with DOM APIs only
  data/data.json         The polluters, scores inputs, evidence and sources
  data/ireland-map.json  County outlines (from the MapSVG Ireland map, CC0), as plain integer rings
  assets/logo.jpg        Threatshade logo
  _headers               Security headers for Cloudflare Pages (CSP, HSTS, etc.)
scripts/
  common.py              Shared helpers and the Python copy of the scoring formula
  fetch_updates.py       Weekly fetch from EPA sources (standard library only)
  validate.py            Strict validation of data.json and the map, plus change warnings
  build_map.py           Rebuilds ireland-map.json from the MapSVG source SVG (only when needed)
config/link_allowlist.json   Hosts that source links and the fetcher may use
data/state/              What the fetcher saw last time (for change detection)
tests/                   Unit tests (python3 -m unittest discover -s tests -v)
.github/workflows/       Weekly refresh (opens a PR) and PR validation
docs/THREAT_MODEL.md     Inputs for the threat model
SECURITY.md              Security controls and how to report a problem
```

## Run it locally

`fetch()` does not work from `file://`, so serve the folder:

```bash
python3 -m http.server 8000 --directory site
# then open http://localhost:8000
```

Run the checks:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/validate.py
```

No packages need installing. Everything uses the Python 3.10+ standard library.

## The county map

County boundaries come from MapSVG's geo-calibrated Ireland map (https://mapsvg.com/maps/ireland/, CC0 1.0, no attribution required; credited on the page anyway). The SVG is not served or embedded. `scripts/build_map.py` converts it into `site/data/ireland-map.json`, which holds only county codes, names and integer outlines, and the app draws the shapes itself. The source map uses a Mercator projection within its stated bounds; `app.js` and `scripts/common.py` share that projection, and a test checks that known towns land in the right county.

To refresh the geometry: download `https://mapsvg.com/maps/geo-calibrated/ireland.svg`, run `python3 scripts/build_map.py ireland.svg`, then run the tests.

The validator warns if any polluter's site falls outside every county, which catches mistyped coordinates.

## How the weekly update works

1. Every Monday the `weekly-data-update` workflow runs `scripts/fetch_updates.py`.
2. The fetcher checks the EPA priority sites list, the EPA prosecutions pages and the EPA LEAP open-data API.
3. It only changes one thing automatically: a polluter's priority-list status (`current` or `past`). New prosecutions, new priority sites and LEAP changes are written to a report for a human to act on.
4. `scripts/validate.py` checks the result and compares it with what is live.
5. If anything changed, the workflow opens a pull request with the report as its description. Nothing goes live until you review and merge it.

To edit data by hand, change `site/data/data.json`, update `last_reviewed`, run the tests and open a pull request.

## Publish to GitHub (account SeanDuggan)

```bash
# create an empty private repo called "threatshade" on GitHub first, then:
git remote add origin https://github.com/SeanDuggan/threatshade.git
git push -u origin main
```

Then in the repository settings:

- **Branch protection on `main`:** require a pull request, require the `validate` check, require review from Code Owners, block force pushes.
- **Actions > General:** workflow permissions "Read repository contents"; allow GitHub Actions to create pull requests (needed for the weekly PR).
- **Security:** turn on Dependabot alerts and secret scanning. Use two-factor authentication on the account.
- Note: pull requests opened with the built-in token do not trigger other workflows, so the weekly job runs the tests and validation itself before opening the PR.

## Deploy to Cloudflare Pages (after the threat model)

- Connect the GitHub repo, production branch `main`.
- Build command: none. Build output directory: `site`.
- `site/_headers` sets the security headers. Check them after the first deploy with `curl -sI https://<your-domain>/`.
- Turn off preview deployments for pull requests from forks, or keep the repo private.

## Before going public

- Get legal advice on naming companies. Every claim must stay tied to a source, and the method and disclaimer must stay on the page.
- Verify the pinned GitHub Action commit (`actions/checkout`, pinned to the v4.2.2 commit) against the official release page. Dependabot will propose updates.
- Self-host the fonts, then remove the Google Fonts hosts from the CSP in `site/_headers`.
- Add a licence file if you want others to reuse the code or data.
