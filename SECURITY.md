# Security

## Reporting a problem

Please report security issues privately using GitHub's "Report a vulnerability" (private vulnerability reporting) on this repository rather than opening a public issue. Factual corrections about a listed organisation can be raised as a normal issue with a link to the source.

## Controls in place

**Public site**
- Static files only: no server-side code, database, authentication, cookies, forms or user input.
- All data is rendered with `textContent` and DOM APIs. A test fails the build if `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write` or `eval(` appear in `app.js`.
- Strict Content-Security-Policy in `site/_headers`: scripts and data only from the site's own origin, no inline scripts or styles, no framing, no form posts, no plugins.
- Source links are allowed only if they are `https://` and on the host allowlist. This is checked in the pipeline and again in the browser.
- HSTS, `nosniff`, `X-Frame-Options: DENY`, a strict referrer policy, a restrictive Permissions-Policy and same-origin COOP/CORP.

**Data pipeline**
- The fetcher uses only the Python standard library, so there are no third-party packages in the supply chain.
- It only contacts allowlisted HTTPS hosts (`www.epa.ie`, `data.epa.ie`) and blocks redirects elsewhere. Responses are limited in size and time.
- Parsed values are bounded. If a source returns an implausible result, for example after a page redesign, that step is skipped and reported instead of applied.
- Automated edits are limited to one field (priority-list status). Everything else requires a human.
- `validate.py` rejects markup, control characters, `javascript:`/`data:` text, out-of-range numbers, unknown source references and coordinates outside Ireland. It warns on score swings of 15+ points, added or removed polluters and name changes.

**Repository and CI**
- Workflows default to no permissions. The weekly job gets only `contents: write` and `pull-requests: write`. The validation job is read-only.
- No repository secrets are used.
- Actions are pinned to full commit SHAs and kept current by Dependabot.
- `persist-credentials: false` on checkout. The token is only made available to the git push step.
- No `pull_request_target` triggers, and workflow context values are passed through environment variables rather than interpolated into shell.
- Changes reach production only through a reviewed pull request (branch protection plus CODEOWNERS).

## Known gaps to consider in the threat model

See `docs/THREAT_MODEL.md`.
