#!/usr/bin/env python3
"""
argosdns_subs.py — subdomain enumeration via the ArgosDNS API.

Pulls every page for a domain and prints ONLY the discovered subdomains
(one per line) to stdout, so it pipes cleanly into other tools:

    ./argosdns_subs.py -d johndeerecloud.com | httpx -silent

Auth token resolution order:
    1. -t / --token flag
    2. ARGOSDNS_TOKEN environment variable
    3. ~/.argosdns_token file (first line)

Examples:
    ./argosdns_subs.py -d johndeerecloud.com
    ./argosdns_subs.py -d deere.com -o deere_subs.txt
    ARGOSDNS_TOKEN=ds_xxx ./argosdns_subs.py -d deere.com --per-page 500
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.parse
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("error: 'requests' not installed. run: pip install --break-system-packages requests")

API = "https://www.argosdns.io/api/v1/subdomains"
DEFAULT_PER_PAGE = 500      # plan max items per request
MAX_PER_PAGE = 500
DEFAULT_DELAY = 1.1         # plan rate limit is 1 req/s — pace above it
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3


def log(msg: str, quiet: bool) -> None:
    """Progress goes to stderr so stdout stays pure subdomain data."""
    if not quiet:
        print(msg, file=sys.stderr)


def resolve_token(cli_token: str | None) -> str:
    if cli_token:
        return cli_token.strip()
    env = os.environ.get("ARGOSDNS_TOKEN")
    if env:
        return env.strip()
    token_file = Path.home() / ".argosdns_token"
    if token_file.is_file():
        first = token_file.read_text(encoding="utf-8").strip().splitlines()
        if first:
            return first[0].strip()
    sys.exit(
        "error: no API token. pass -t <token>, set ARGOSDNS_TOKEN, "
        "or put it in ~/.argosdns_token"
    )


def fetch_page(session: requests.Session, domain: str, page: int, per_page: int,
               quiet: bool) -> dict | None:
    endpoint = (
        f"{API}?domain={urllib.parse.quote(domain)}"
        f"&per_page={per_page}&page={page}"
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(endpoint, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            log(f"[!] page {page}: request error ({e}); retry {attempt}/{MAX_RETRIES}", quiet)
            time.sleep(2 * attempt)
            continue

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                log(f"[!] page {page}: non-JSON 200 response, stopping", quiet)
                return None
        if resp.status_code == 401:
            sys.exit("error: 401 Unauthorized — bad or expired token.")
        if resp.status_code == 402:
            sys.exit("error: 402 — monthly quota exhausted (6,000/mo plan).")
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 5 * attempt))
            log(f"[!] page {page}: 429 rate-limited, sleeping {wait}s", quiet)
            time.sleep(wait)
            continue
        # 4xx other than the above are usually terminal (e.g. bad domain)
        log(f"[!] page {page}: HTTP {resp.status_code}, stopping", quiet)
        return None

    log(f"[!] page {page}: gave up after {MAX_RETRIES} retries", quiet)
    return None


def enumerate_domain(token: str, domain: str, per_page: int,
                     max_pages: int | None, delay: float, quiet: bool) -> set[str]:
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "argosdns-subs/1.0",
    })

    findings: set[str] = set()
    page = 1
    while True:
        if max_pages is not None and page > max_pages:
            log(f"[*] reached --max-pages {max_pages}, stopping", quiet)
            break

        data = fetch_page(session, domain, page, per_page, quiet)
        if not isinstance(data, dict):
            break

        items = data.get("data", [])
        if not isinstance(items, list) or not items:
            break

        new = 0
        for item in items:
            # API may return plain strings or objects — handle both
            sub = None
            if isinstance(item, str):
                sub = item
            elif isinstance(item, dict):
                sub = item.get("subdomain") or item.get("hostname") or item.get("name")
            if sub:
                sub = sub.strip().lower().rstrip(".")
                if sub and sub not in findings:
                    findings.add(sub)
                    new += 1

        log(f"[*] page {page}: +{new} new  (total {len(findings)})", quiet)

        meta = data.get("meta", {})
        if not isinstance(meta, dict) or not meta.get("has_more"):
            break
        page += 1
        if delay > 0:
            time.sleep(delay)   # respect the 1 req/s plan rate limit

    return findings


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Subdomain enumeration via the ArgosDNS API (prints only subdomains).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("-d", "--domain", required=True, help="target apex domain")
    ap.add_argument("-t", "--token", help="ArgosDNS API token (else ARGOSDNS_TOKEN / ~/.argosdns_token)")
    ap.add_argument("-o", "--output", help="also write results to this file")
    ap.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE,
                    help=f"items per request (max {MAX_PER_PAGE})")
    ap.add_argument("--max-pages", type=int, default=None,
                    help="safety cap on pages (protects monthly quota; each page = 1 request)")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                    help="seconds between requests (plan rate limit is 1 req/s)")
    ap.add_argument("-q", "--quiet", action="store_true", help="suppress progress on stderr")
    args = ap.parse_args()

    per_page = max(1, min(args.per_page, MAX_PER_PAGE))
    token = resolve_token(args.token)

    log(f"[*] argosdns enum: {args.domain} (per_page={per_page}, delay={args.delay}s)", args.quiet)
    subs = enumerate_domain(token, args.domain, per_page, args.max_pages, args.delay, args.quiet)

    ordered = sorted(subs)
    for s in ordered:
        print(s)

    if args.output:
        Path(args.output).write_text("\n".join(ordered) + ("\n" if ordered else ""), encoding="utf-8")
        log(f"[+] wrote {len(ordered)} subdomains -> {args.output}", args.quiet)

    log(f"[+] done: {len(ordered)} unique subdomains", args.quiet)


if __name__ == "__main__":
    main()
