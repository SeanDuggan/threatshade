# Security

## Reporting a problem

Email **security@threatshade.com**. Please do not open a public issue for security problems. Factual corrections about a listed organisation can be raised as a normal issue with a link to the source.

Threatshade is a volunteer project with no budget, so there is no bug bounty, but we will credit reporters who want it. The full policy (response times, scope, safe harbour) is in `site/security-policy.txt`, published at https://threatshade.com/security-policy.txt. The machine-readable contact is `site/.well-known/security.txt` (RFC 9116), published at https://threatshade.com/.well-known/security.txt.

`security.txt` has an `Expires` date (currently 2027-11-01). Update it before then, and keep it less than a year ahead.

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
