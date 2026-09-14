#!/usr/bin/env python3
"""Inject SHA-256 CSP hashes for inline scripts into public/_headers.

Run AFTER `hugo --gc --minify`: minification changes the exact bytes that
get hashed, and the hash must match what ships.
"""
import base64
import hashlib
import re
import sys
from pathlib import Path

PUBLIC = Path("public")
HEADERS = PUBLIC / "_headers"
PLACEHOLDER = "__SCRIPT_HASHES__"

# <script> blocks with no src attribute — i.e. the inline ones.
INLINE_SCRIPT = re.compile(
    r"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>",
    re.DOTALL | re.IGNORECASE,
)


def main() -> int:
    if not HEADERS.is_file():
        print("error: public/_headers not found — did hugo run?", file=sys.stderr)
        return 1

    hashes = set()
    for page in PUBLIC.rglob("*.html"):
        html = page.read_text(encoding="utf-8", errors="replace")
        for body in INLINE_SCRIPT.findall(html):
            if not body.strip():
                continue
            digest = hashlib.sha256(body.encode("utf-8")).digest()
            hashes.add("'sha256-" + base64.b64encode(digest).decode() + "'")

    text = HEADERS.read_text(encoding="utf-8")
    if PLACEHOLDER not in text:
        print("error: placeholder missing from _headers", file=sys.stderr)
        return 1

    HEADERS.write_text(text.replace(PLACEHOLDER, " ".join(sorted(hashes))), encoding="utf-8")
    print(f"csp: injected {len(hashes)} inline script hash(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
