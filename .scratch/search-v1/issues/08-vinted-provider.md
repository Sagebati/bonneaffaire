# 08: Vinted Provider

**What to build:** Vinted (vinted.fr) as a Provider, wrapping whichever of `vinted_scraper` and `vinted-api-kit` is healthier at implementation time. Both use the new `svc-catalogue` endpoint that replaced the old one in October 2026. It uses an anonymous session and supports:
- Search: keywords, price range, Condition, sort
- Native URLs from vinted.fr
- Listing details

Vinted's buyer protection is captured as a Buyer fee, so Total cost is computed when Shipping is known. Vinted's condition labels map to Condition, with the raw label kept. Seller kind distinguishes Vinted Pro sellers. The country setting defaults to France.

**Blocked by:** 02, 03, 04, 05

**Status:** ready-for-agent

- [x] A keyword Search, a Filtered Search, and a pasted Vinted URL all return Vinted Listings via the CLI
- [x] Listing details work for a Vinted Listing
- [x] Buyer fee, Price in cents, Condition mapping (e.g. "Neuf avec étiquette", "Très bon état") and Seller kind are correct in fixture tests built from recorded responses
- [x] Blocked responses (403 from Cloudflare or DataDome) produce outcome blocked; an unexpected shape produces failed
- [x] The chosen library and the reason for choosing it are noted in the ticket's comments
- [x] A live canary test for Vinted exists, excluded from the default run

## Comments

**Library choice (2026-11-08): `vinted_scraper` 5.2.0 (Giglium), not `vinted-api-kit` 1.3.1.**

- Both use the new `svc-catalogue` endpoint and an anonymous session taken from the landing page.
- `vinted_scraper` is the more active of the two: 5.2.0 came out on 2026-11-05, and `vinted-api-kit` last released on 2026-10-21.
- `vinted-api-kit` no longer offers Listing details: `item_details()` always raises `VintedDeprecatedError`. `vinted_scraper` still reads the public item page.
- `vinted_scraper` is built on httpx, which we already use. Its `config` passes an httpx transport straight to its clients, so tests feed recorded responses into the library's own HTTP client, as the spec's Seam 2 asks. `vinted-api-kit` would add curl_cffi.
- Its async wrapper returns raw JSON, so we map fields ourselves and don't depend on its models.

**Implementation notes**

- Buyer fee comes from `service_fee` on search items and from `pricingServices.buyerProtection.finalPrice` on the item page. Search results carry no Shipping, so Total cost is only known from Listing details, which read the cheapest delivery price (`pricingServices.shipping.finalPrice`).
- Condition mapping: "Neuf avec étiquette" and "Neuf sans étiquette" are New, "Très bon état" is LikeNew, "Bon état" and "Satisfaisant" are Used. Any other label is Unknown. The raw label is always kept. Native condition filter IDs are `6,1` / `2` / `3,4`; the IDs for New (6 and 1) were checked live. Refurbished or ForParts alone return no Listings and send no request.
- Seller kind comes from `user.business` in search results and from the `user_info_header` plugin on the item page. Vinted Pro sellers are Professional.
- The library's `item()` reads only the page `<head>`, which has no price, condition or fees. Listing details therefore fetch the full page through the wrapper's own site client (`_client` and `_build_page_headers()`, which are private) and parse its JSON-LD and Next.js flight data. If the library changes, this is the place to check.
- Failures: the library raises a bare RuntimeError. A transport wrapper records the last HTTP status: 403 or 429 means blocked, 404 or 410 means not found, anything else is an unexpected shape. The session fetch is not retried, so a blocked landing page costs one request.
- Search fetches one page only, at most 96 Listings.
- Fixtures are real recordings, trimmed. See `tests/fixtures/vinted/SOURCES.md`.
