---
title: "This Website"
date: 2026-09-20
draft: false
summary: "A static personal site on Hugo and Cloudflare Workers, hardened to A+ across the standard scanners, with a build-time script that keeps the Content-Security-Policy from going stale."
tags: ["hugo", "cloudflare", "csp", "dns", "python", "static-site"]
ShowToc: true
TocOpen: false
---

The site you are reading is itself a project. This page documents how it is built,
which trade-offs I made, and where it still falls short.

Source: [github.com/ffallahi1/farhadfallahi.dev](https://github.com/ffallahi1/farhadfallahi.dev)

## Goals and constraints

I needed a way to demonestrate my skills and to publish writeups. The easiest 
option was WordPress on a cheap VPS, or a drag-and-drop site on a
managed platform. I wanted something more challenging and more technical,
so I rejected both

WordPress running on a VPS needs constant maintenance and is a real liability. 
As someone who wants to work in security, a vulnerable plugin on my website would
be the worst advertisement. A managed platform solves that but then it didn't leave 
anything to demonstrate and nothing to inspect.

So I set four constraints:

- **Under $15 a year, total.** I am a student.
- **No server to patch.** No runtime, no database, no admin login.
- **Auditable end to end.** Every byte a visitor receives should be traceable
  to a file in a public repository.
- **Maintainable by one person during a degree.** Any workflow that takes more
  than one command to publish would go unused.

## Stack

| Layer | Choice |
| --- | --- |
| Generator | Hugo (extended), PaperMod theme, vendored |
| Hosting | Cloudflare Workers with static assets |
| Build | Workers Builds, triggered by push to `main` |
| Registrar / DNS | Cloudflare Registrar, DNSSEC enabled |
| Mail | Cloudflare Email Routing (receive only) |
| Third-party scripts | None |

That last row is a design decision, not an omission. I return to it below.

## Supply chain

Hugo distributes as a single static Go binary with no runtime dependencies. The
main alternative I considered was Astro, which is more flexible and has better
component ergonomics, but a default Astro project pulls in several hundred npm
packages. For a site whose entire output is static HTML, that is a large
transitive dependency tree to accept in exchange for features I do not need.

I applied the same reasoning to the theme. Rather than adding PaperMod as a git
submodule or a Hugo module, I cloned it, deleted its `.git` directory, and
committed the files into my own repository. Three consequences:

1. The build fetches nothing from the internet at deploy time.
2. Upstream cannot change what ships to visitors without an explicit commit
   from me.
3. Every line of template and CSS that reaches a browser is reviewable in my
   repository, at the revision that produced the live site.

The cost is that theme updates are manual. This matters less than it sounds,
because Hugo's template lookup order means I never edit files inside `themes/`
anyway. Any customisation goes in `layouts/` at the project root and takes
precedence, so re-vendoring the theme cannot clobber my work.

## Build and deploy

Deployment configuration lives in `wrangler.jsonc`, in version control, rather
than in dashboard fields:

```jsonc
{
  "name": "farhadfallahi-dev",
  "compatibility_date": "2026-09-13",
  "build": {
    "command": "hugo --gc --minify && python3 tools/csp_hashes.py"
  },
  "assets": {
    "directory": "./public",
    "not_found_handling": "404-page"
  }
}
```

Pushing to `main` triggers a build and deploy. Pushing to any other branch
produces an isolated preview URL, which is how I check a draft renders
correctly before it goes public. The Hugo version is pinned with a
`HUGO_VERSION` build variable so the CI build matches my local one.

Once the custom domain was attached I disabled the `*.workers.dev` route. Two
publicly reachable copies of the same content is a loose end.

## The interesting part: a CSP that does not rot

I wanted `script-src 'self'` with no `'unsafe-inline'`. PaperMod ships inline
scripts, most importantly the anti-flicker snippet in `<head>` that applies the
saved colour scheme before first paint. The standard way to permit a specific
inline script under a strict policy is to whitelist its SHA-256 hash.

Hardcoding those hashes is a trap. They change whenever the theme or the
config changes, and minification alters the exact bytes that get hashed, so the
hash has to be computed *after* the build, not from the source template. Worse,
the failure is quiet: a stale hash does not break the build, it just stops
matching.

So I generate them at build time. `static/_headers` contains a placeholder:

```
Content-Security-Policy: default-src 'self'; script-src 'self' __SCRIPT_HASHES__; ...
```

And a short Python script runs immediately after Hugo, walking the built output
and substituting real hashes:

```python
INLINE_SCRIPT = re.compile(
    r"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>",
    re.DOTALL | re.IGNORECASE,
)

hashes = set()
for page in Path("public").rglob("*.html"):
    html = page.read_text(encoding="utf-8", errors="replace")
    for body in INLINE_SCRIPT.findall(html):
        if body.strip():
            digest = hashlib.sha256(body.encode("utf-8")).digest()
            hashes.add("'sha256-" + base64.b64encode(digest).decode() + "'")
```

The negative lookahead is doing the real work: it matches `<script>` elements
that have no `src` attribute, which is exactly the set of inline scripts the
policy needs to account for.

The failure mode is deliberate. If the script does not run, the literal
`__SCRIPT_HASHES__` string ships inside the policy. Browsers ignore source
expressions they do not recognise, so the policy degrades to plain
`script-src 'self'` — stricter, not looser — and the theme toggle visibly
breaks. It fails closed and it fails loudly.

### A trade-off I accepted

`style-src` still carries `'unsafe-inline'`. PaperMod uses inline `style`
attributes across several layouts, and removing them would mean forking a
substantial portion of the theme. Inline CSS cannot execute code; the injection
risk it carries is narrow compared to inline script. I judged the maintenance
cost higher than the residual risk and drew the line there on purpose. It is on
the list below.

## Response headers

Set in `static/_headers`, which Cloudflare reads as configuration rather than
serving as a file:

- `Strict-Transport-Security` — two years, `includeSubDomains`, `preload`.
  Somewhat redundant on a `.dev` domain, since the whole TLD is on the HSTS
  preload list, but the header makes the policy explicit.
- `X-Content-Type-Options: nosniff` — no MIME sniffing.
- `X-Frame-Options: DENY` and `frame-ancestors 'none'` — no framing, no
  clickjacking.
- `Referrer-Policy: strict-origin-when-cross-origin` — outbound links leak the
  origin, never the path.
- `Permissions-Policy` — explicitly denies camera, microphone, geolocation,
  payment, USB and the rest. A blog has no business asking for hardware.
- `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy` — origin
  isolation.
- `Cache-Control: public, max-age=31536000, immutable` scoped to `/assets/*`.
  Hugo fingerprints those filenames with a content hash, so a one-year cache is
  safe. HTML stays uncached and updates immediately on deploy.

HSTS is sent from this file and *not* from Cloudflare's dashboard toggle. Two
mechanisms setting the same header means two places to check and a risk of
duplication. The file is in git, so it diffs and reviews.

## DNS and mail

- **DNSSEC** enabled at the registrar.
- **CAA** records restricting issuance to Cloudflare's certificate authorities,
  plus an `iodef` record so I am notified of unauthorised issuance attempts.
- **DMARC** at `p=reject`. The domain receives mail through Cloudflare Email
  Routing but never sends any, so there is no legitimate traffic to
  false-positive on. Anything claiming to be from this domain that fails
  authentication should be discarded, and `p=reject` says so unambiguously.
- **security.txt** at `/.well-known/security.txt` per RFC 9116, with a real
  contact address and an `Expires` field I have a calendar reminder to renew.

## No analytics

I originally planned to add Cloudflare Web Analytics. I dropped it. Adding it
means loading a script from a third-party origin, which means widening the CSP
I had just spent the effort tightening. For a personal site the data would not
change any decision I make. A policy with no third-party origins at all is
worth more to me than a visitor counter.

## Repository controls

Every commit is signed with an SSH key, starting from the first one. A branch
ruleset on `main` blocks force pushes and deletions and requires signed
commits. Secret scanning and push protection are on, which blocks a commit
containing a recognised credential before it leaves my machine — a reasonable
precaution for a repository that will accumulate lab writeups and scripts.

The Cloudflare GitHub app is scoped to this one repository rather than granted
account-wide read access.

## Verification



| Scanner | Result |
| --- | --- |
| securityheaders.com | A+ |
| MDN Observatory | A+ |
| Qualys SSL Labs | A+ |
| internet.nl | 95 |

## Known gaps and next steps

- Move PaperMod's inline scripts into external files. That removes the need for
  hash generation entirely and simplifies the policy.
- Eliminate `'unsafe-inline'` from `style-src` once the above is done.
- Add a CSP reporting endpoint so violations are observable rather than
  invisible.
- Add a CI check that asserts the expected header set against the deployed URL,
  so a regression fails the build instead of quietly shipping.

## Cost

$12 a year for the domain. Everything else runs on free tiers.
