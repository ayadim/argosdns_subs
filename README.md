# argosdns_subs.py

Subdomain enumeration via the [ArgosDNS](https://www.argosdns.io) API. Pulls **every page** for a
domain and prints **only the discovered subdomains** (one per line) to stdout, so it pipes cleanly
into any downstream recon tool.

---

## Features

- Single required argument: `-d <domain>`.
- Auto-paginates using the API's `meta.has_more` flag (500 items/request).
- Outputs **only subdomains** — deduplicated, lowercased, sorted — to stdout. Progress goes to stderr.
- Respects the plan **rate limit (1 req/s)** with configurable pacing (`--delay`, default 1.1s).
- Quota-safe: `--max-pages` caps the number of API calls.
- Graceful handling of `401` (bad token), `402` (quota exhausted), `429` (rate-limited, backs off and retries).
- Zero third-party deps except `requests`.

---

## Requirements

- Python 3.9+
- `requests`

```bash
pip install --break-system-packages requests
```

---

## Authentication

The API token is resolved in this order (first match wins):

1. `-t / --token` flag
2. `ARGOSDNS_TOKEN` environment variable
3. `~/.argosdns_token` file (first line)

```bash
# option A — env var (recommended)
export ARGOSDNS_TOKEN=ds_xxxxxxxxxxxxxxxx

# option B — inline flag
~/Desktop/argosdns_subs.py -d deere.com -t ds_xxxxxxxxxxxxxxxx

# option C — persist to a file
echo ds_xxxxxxxxxxxxxxxx > ~/.argosdns_token
chmod 600 ~/.argosdns_token
```

---

## Usage

```
argosdns_subs.py -d DOMAIN [-t TOKEN] [-o OUTPUT] [--per-page N] [--max-pages N] [--delay S] [-q]
```

| Flag | Description | Default |
|------|-------------|---------|
| `-d`, `--domain` | Target apex domain (**required**) | — |
| `-t`, `--token` | API token (else `ARGOSDNS_TOKEN` / `~/.argosdns_token`) | — |
| `-o`, `--output` | Also write results to this file | — |
| `--per-page` | Items per request (max 500) | `500` |
| `--max-pages` | Safety cap on pages (each page = 1 request) | none |
| `--delay` | Seconds between requests (rate limit is 1 req/s) | `1.1` |
| `-q`, `--quiet` | Suppress progress output on stderr | off |

---

## Examples

```bash
# basic — print all subs to screen
~/Desktop/argosdns_subs.py -d johndeerecloud.com

# save to a file (also still prints to stdout)
~/Desktop/argosdns_subs.py -d deere.com -o deere_subs.txt

# pipe straight into another tool
~/Desktop/argosdns_subs.py -d johndeerecloud.com | httpx -silent
~/Desktop/argosdns_subs.py -d johndeerecloud.com -q | dnsx -silent | nuclei -silent

# cap API spend on a huge domain (only first 5 pages = 5 requests)
~/Desktop/argosdns_subs.py -d deere.com --max-pages 5
```

---

## Output

- **stdout** — one subdomain per line, nothing else (safe to pipe).
- **stderr** — per-page progress, e.g. `[*] page 3: +500 new  (total 1500)`.

Example:

```
access-control-api-gateway.ghns-integration-enablement-devl-standalone.us.e00.c01.johndeerecloud.com
act.ghns-web-platform-r2-prod-standalone5.eu.e00.c01.johndeerecloud.com
aiops.ghns-autobiz-prod-vpn.use1.e00.c01.johndeerecloud.com
...
```

---

## Plan / quota notes

ArgosDNS **Professional** plan constraints the tool is tuned for:

| Limit | Value |
|-------|-------|
| Requests | 6,000 / month |
| Items per request | 500 |
| Rate limit | 1 req/s |
| API keys | 1 |

- Each page = **1 request**. A domain with N subdomains costs `ceil(N / 500)` requests.
- Example: `johndeerecloud.com` (~7,700 subs) = **16 requests**, ~18s at default pacing.
- 6,000 req/month ≈ **375** enums of that size.
- The tool is single-threaded on purpose — it matches the 1 req/s / 1-key plan exactly.

---

## Exit behavior

| Condition | Behavior |
|-----------|----------|
| `401 Unauthorized` | Exits with an error (bad/expired token) |
| `402 Payment Required` | Exits — monthly quota exhausted |
| `429 Too Many Requests` | Honors `Retry-After`, backs off, retries |
| Network error | Retries up to 3× with increasing delay |
| Empty page / `has_more=false` | Stops cleanly |

---

## Disclaimer

For use only against domains you are **authorized** to test (bug bounty scope, owned assets,
signed engagements). You are responsible for staying within program rules and applicable law.
