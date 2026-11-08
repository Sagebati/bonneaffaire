# Prior art: multi-marketplace search and price tracking (2026-11-08)

No maintained OSS aggregates Vinted + Leboncoin + eBay. Projects fall into: (A) single-product price trackers, (B) single-marketplace listing-alert bots, (C) single-marketplace MCP servers.

## A. Price trackers
- **[PriceBuddy](https://github.com/jez500/pricebuddy)** (PHP, 1.5k★) + [pricebuddy-cli](https://github.com/jez500/pricebuddy-cli) (Go, MCP). Config-driven stores: per-field `{type, value}` extractors (schema_org/css/xpath/regex/jsonpath), fetch backend Http or headless. `Product 1→N Url 1→N Price`. `product_sources` with `search_url`. CLI keeps a SQLite mirror; agent-friendly `--agent --select`, `--json`.
- **[Discount Bandit](https://github.com/Cybrarist/Discount-Bandit)** (PHP, 761★). Code-per-store `StoreTemplate` (get_price, get_used_price, get_shipping_price, get_condition, …, bot-detected hook). Prices as integer minor units, new/used side by side, one history row per link per day.
- **[PriceGhost](https://github.com/clucraft/PriceGhost)** (TS, 1.1k★). Multi-strategy price extraction (JSON-LD, site scraper, CSS, LLM) with voting; LLM catches "Save $200" / "$49/mo" misreads.
- **[changedetection.io](https://github.com/dgtlmoon/changedetection.io)** (Python, 35k★). Pluggy processors/fetchers; restock/price processor on structured data.

## B. Listing-alert bots
- **[vinted-bot](https://github.com/jasp-nerd/vinted-bot)** (Python) — best engineered; read its [architecture.md](https://github.com/jasp-nerd/vinted-bot/blob/main/docs/architecture.md). Swappable transport (httpx / curl_cffi / replay-from-disk for tests). Anonymous per-domain sessions, rotated. Typed errors: 401 refresh token, 403 back off hard + new session, 429 honor Retry-After, 200-wrong-shape log only. Per-search dedup (`query_items`: seeded/matched/rejected), id floor, freshness window, silent first run. Transactional outbox. Tiered filters incl. total price with buyer fee; deal = below rolling median of the search's own matches. Rejections stored with reason. Item watches detect reserved/sold/removed. Weekly live canary in CI.
- **[ai-marketplace-monitor](https://github.com/BoPeng/ai-marketplace-monitor)** (Python, 408★). TOML marketplace/item config with fallbacks; Condition/DeliveryMethod/SortBy enums; content-hash dedup; LLM rates listings 1–5. Requires logged-in Facebook (account risk).
- **[lbc-finder](https://github.com/etienne-hd/lbc-finder)** — thin `Search(name, parameters, delay, handler)` over `lbc`.
- **[MarketPlaceLens](https://github.com/AlexRosbach/MarketPlaceLens)** — connectors take a provider search URL, local filters on top; normalised review queue.
- [Vinted-Notifications](https://github.com/Fuyucch1/Vinted-Notifications).

## C. MCP servers
- **[googlarz/vinted-mcp-cli](https://github.com/googlarz/vinted-mcp-cli)** (TS): one core → MCP + CLI + npm. `search_items`, `get_new_items(afterId)`, `get_item`, `get_seller`, `compare` across countries, name→ID resolvers, proxy, cache.
- [andrijdavid/vinted-mcp](https://github.com/andrijdavid/vinted-mcp): countries/categories as MCP resources; stdio or Streamable HTTP.
- **[wydii/leboncoin-mcp](https://github.com/wydii/leboncoin-mcp)**: `search_ads` takes structured filters *or* a Leboncoin URL; `get_ad`, `get_user`, category/region lists.
- **[hanku4u/ebay-mcp-server](https://github.com/hanku4u/ebay-mcp-server)** (Python, Browse API): `search_ebay`, `track_price`, `get_price_history`, `find_deals`; SQLite.

## D. Hardware $/TB
- [daveed716/scripts best_sata_drive_deals.py](https://github.com/daveed716/scripts): eBay Browse + SerpAPI Amazon + ServerPartDeals; capacity regex; total = price + shipping; $/TB.
- [devoidx/price-tracker](https://github.com/devoidx/price-tracker): NAS drives, known selectors per retailer, daily FX.

## Patterns to steal
1. Two tracked kinds: saved-search watch (cursor/id floor, seeded/matched/rejected) and product watch (canonical product ← many listings). Market price = stats over matched listings.
2. Provider interface with typed capabilities (search, get_item, get_seller, new_since(cursor)) and declarative filter vocabulary; accept native search URLs.
3. Raw + normalised: integer minor units + currency, shipping and buyer fee separate, Condition enum + raw string.
4. Listing lifecycle: active/reserved/sold/removed/price_changed.
5. Typed error handling, per-provider session rotation, replay transport for tests, live canary.
6. Product identity in stages: regex/attributes/EAN first, LLM as fallback with stored confidence.
7. Explainability: store rejection reasons; compact JSON projections for agents.

## Pitfalls
Uniform retries (turn 403 into bans); notifying on first run; timestamp-only dedup; logged-in scraping; price as string/float; ignoring buyer fee and shipping; datacenter IPs.
