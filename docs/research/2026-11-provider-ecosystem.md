# Provider access and language ecosystem (2026-11-08)

Sources: GitHub / crates.io APIs, cloned client repos, official docs. Facts as of 2026-11-08; endpoints churn.

## eBay
- Official **Browse API** usable by an individual developer account (OAuth client credentials). Default 5,000 calls/day ([limits](https://developer.ebay.com/develop/api/buy/api_call_limits)); free [Application Growth Check](https://developer.ebay.com/api-docs/static/gs_request-an-application-growth.html) raises it. Limits page footnotes "Buy APIs require an additional license".
- Browse returns **active listings only**.
- Sold data: Finding API `findCompletedItems` decommissioned 2025-02-05. [Marketplace Insights API](https://developer.ebay.com/api-docs/buy/marketplace-insights/overview.html) is limited release; individuals reportedly refused. Scraping `/sch/...&LH_Sold=1&LH_Complete=1` is the remaining route (Akamai protection claimed by vendor blogs, unverified).

## Vinted
- No official search API for individuals ([Pro Integrations](https://pro-docs.svc.vinted.com) is allowlist-only, inventory/orders).
- Anti-bot: Cloudflare + DataDome, TLS fingerprint checks, datacenter IPs rejected.
- **`/api/v2/catalog/items` removed October 2026.** New search: `https://api.<domain>/svc-catalogue/items` with `attribute_ids[...]` filters and a `locale` header (vinted.com → `api.www.vinted.com`). See [vinted-api-kit CHANGELOG](https://github.com/vlymar1/vinted-api-kit/blob/main/CHANGELOG.md) v1.1.0.
- Anonymous session: load homepage first to get `access_token_web` cookie.
- Still used: `/api/v2/users/{id}`, `/api/v2/wardrobe/{id}/items`.
- Per-country domains: .fr, .de, .es, .it, .co.uk, .cz, .sk, .se, .com, …

## Leboncoin
- No official API. DataDome; needs a clean French residential IP.
- Search: `POST https://api.leboncoin.fr/finder/search`. Ad detail: `/api/adfinder/v1/classified/{id}`. User: `/api/user-card/v2/{id}/infos`.

## Open-source clients

| Provider | Python | TS/Node | Go | Rust |
|---|---|---|---|---|
| Leboncoin | [etienne-hd/lbc](https://github.com/etienne-hd/lbc) (224★, 2026-11-03, curl_cffi `impersonate="chrome"`, `DatadomeError` on 403) | [tdurieux/leboncoin-api](https://github.com/tdurieux/leboncoin-api) dead (2023) | none | [lbc-rs](https://github.com/lheintzmann1/lbc-rs) 0.1.1, plain reqwest |
| Vinted | [vinted-api-kit](https://github.com/vlymar1/vinted-api-kit) (curl_cffi, svc-catalogue, 2026-10-21); [Giglium/vinted_scraper](https://github.com/Giglium/vinted_scraper) (107★, httpx, svc-catalogue, 2026-11-05); pyVinted stale | bots only | [2spy/Vinted-Discord-Bot](https://github.com/2spy/Vinted-Discord-Bot) | `vinted-rs` 0.11 (old endpoint), `vinted-core` 0.2.0 |
| eBay | official SDKs / OpenAPI codegen | same | same | stale crates; codegen |

## Anti-bot HTTP and browsers
- **Python**: curl_cffi (6.8k★), [camoufox](https://github.com/daijro/camoufox) (13k★), nodriver, zendriver, pydoll, Playwright, Scrapling, rnet (wraps wreq).
- **Rust**: [wreq](https://github.com/0x676e67/wreq) (ex-rquest, BoringSSL impersonation, 6.0.0-rc.31, single maintainer). Browsers: chromiumoxide, headless_chrome, fantoccini — no stealth patches, no camoufox/nodriver equivalent.
- **Go**: bogdanfinn/tls-client, utls, CycleTLS; chromedp, rod.
- **TS**: Playwright/Puppeteer + stealth, Ulixee Hero; TLS impersonation needs native bindings.

## Bottom line
Python has the only maintained clients for all three providers and the best stealth tooling. Rust's transport gap is small, its client and stealth-browser gaps are large. See ADR-0001.

Caveat: Vinted and Leboncoin terms of service prohibit automated access.
