# Retailer access: Amazon.fr, LDLC, Back Market (2026-11-08)

Method: web/GitHub/docs, plus one plain `curl` (Chrome UA, no TLS impersonation) per site from a dev machine (not the NAS). Impersonation verdicts are inferred, not tested.

## Amazon.fr — hard
- **PA-API 5.0 is deprecated**, replaced by the **Creators API** (OAuth2, new credentials); old endpoints return 403 ([notice](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/paapiv5-deprecation); docs cite both 2026-04-30 and 2026-05-15). Access requires an Associates account with **10 qualifying sales in the last 30 days** and is lost after 30 days without sales ([intro](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction)). 1 TPS / 8,640 per day initially ([rates](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/concepts/api-rates)). OffersV2 has Condition + SubCondition but **only the featured (Buy Box) offer** ([OffersV2](https://affiliate.amazon.co.jp/creatorsapi/docs/en-us/api-reference/resources/offersV2)).
- Anti-bot: `/s?k=...` returned **HTTP 202 `x-amzn-waf-action: challenge`** (AWS WAF JS challenge); classic `/errors/validateCaptcha` also exists.
- Data: server-rendered search HTML (`data-asin` cards), no JSON-LD. Other offers via the "Autres vendeurs" AOD ajax fragment (HTML). Renewed = separate ASINs; Warehouse appears as used offers from Amazon's resale programme (name unverified).
- Libraries: [python-amazon-paapi](https://github.com/sergioteula/python-amazon-paapi) (wraps Creators API, 2026-09); [amazon-scraper-python](https://github.com/tducret/amazon-scraper-python) (old code). MCP: [HasData/amazon-mcp](https://github.com/HasData/amazon-mcp) (paid API), [Fewsats/amazon-mcp](https://github.com/Fewsats/amazon-mcp).

## LDLC — easy
- No public API; no verified affiliate feed.
- Plain curl → **HTTP 200** on `/recherche/disque%20dur/`, `server: ldlc`, no anti-bot markers, no JS needed.
- Search: server-rendered, 48 `pdt-item` cards/page, links `/fiche/PBxxxxxxxx.html` with price. Product page: JSON-LD Product/Offer with `price`, `priceCurrency`, `availability`, `itemCondition`, `gtin13`, `sku`, AggregateRating. Almost everything is new. Shipping not researched.
- No maintained library or MCP.

## Back Market — moderate to hard
- Official API is seller-only ([api.backmarket.dev](https://apis.io/providers/back-market/)); no catalogue search API.
- Plain curl → **HTTP 403 Cloudflare** `{"code":"bot-need-challenge"}`. Likely needs a real browser. A private mobile API is reportedly used by one Apify scraper.
- Page data structure unverified (blocked).
- Grades: **Premium > Parfait état > Très bon état > État correct** (all four for phones/tablets/laptops/desktops/watches; others only Parfait/Très bon). Premium may include open-box. English: Excellent/Good/Fair. Hard drives are a thin category.
- No maintained library or MCP.
