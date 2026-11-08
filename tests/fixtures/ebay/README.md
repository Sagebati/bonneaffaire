# eBay Browse API fixtures

No eBay credentials existed when these were made, so nothing here was recorded from the live API.

- `search-doc-sample-iphone-price-condition.json`: verbatim response body of the "Return Items
  Based on Price and Condition" sample in eBay's official `item_summary/search` documentation
  (developer.ebay.com, taken from the web.archive.org copy of 2026-01-22). US marketplace, USD,
  no `sellerAccountType` (eBay returns it only on European sites).
- `item-doc-sample.json`: verbatim response body of the "Get Item Details" sample in eBay's
  official `getItem` documentation (same source).
- `search-fr-disque-dur-8-to.json`, `item-fr-176345678901.json`: hand-built for EBAY_FR from the
  field names and types of the official Browse OpenAPI contract (`buy_browse_v1_oas3.json`). They
  cover what the doc samples lack: `sellerAccountType`, CALCULATED shipping, several shipping
  options, French condition labels. Item IDs, sellers and images are invented.
- `token-response.json`: shape of the OAuth client-credentials token response in eBay's OAuth
  documentation; the token is fake.

Replace them with recorded responses once credentials exist. `uv run pytest -m canary` checks
that the live API still parses.
