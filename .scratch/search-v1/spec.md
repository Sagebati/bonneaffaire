# Spec: Search v1

Status: resolved

## Problem Statement

I want to know what something actually costs on the French market, new and second-hand. Hard disks are the motivating case. To find out today I have to search Vinted, Leboncoin, eBay and LDLC one by one. Each has its own filters, condition labels, fee rules and page layout, so comparing them by hand is slow and error-prone. My AI agents can't do it for me either: none of these sites offers a usable API for an individual, except eBay. Existing open-source tools cover one marketplace each, or follow single product pages, and none combines second-hand and retail Providers behind one interface.

## Solution

bonneaffaire is a private, single-user service running on my Synology NAS. One Search runs across several Providers at once and returns Listings in a single normalised shape:
- Price in cents with currency, plus Shipping, Buyer fee and Total cost when known
- a canonical Condition with the Provider's own wording kept alongside
- Seller kind and a link back to the Provider

Each Search also reports a Provider outcome for every Provider asked, so "nothing found" is never confused with "couldn't look". I can fetch full details for any one Listing.

I use it from a CLI. My agents use it through an MCP server, reachable from outside my home network only through a Cloudflare Tunnel protected by Cloudflare Access.

v1 Providers are Vinted, Leboncoin, eBay and LDLC. Amazon and Back Market follow in v1.1 as best-effort Providers, and the design accepts them without changes. Monitoring (saved searches, price history) is a later phase and not part of this spec.

## User Stories

### Searching

1. As the owner, I want to run one Search across all enabled Providers, so that I see the whole market without visiting each site.
2. As the owner, I want to limit a Search to chosen Providers, so that I can focus on second-hand or on retail.
3. As the owner, I want to search by keywords, so that I can describe what I'm looking for in plain words like "disque dur 8 To".
4. As the owner, I want to set a minimum and maximum Price, so that obviously wrong or out-of-budget Listings are excluded.
5. As the owner, I want to filter by Condition (New, Refurbished, LikeNew, Used, ForParts), so that I can compare the new and used markets separately.
6. As the owner, I want to sort merged results by Price or by recency, so that the cheapest or newest Listings come first across all Providers.
7. As the owner, I want to filter Leboncoin by location or radius, so that I can find hand-delivery deals near me.
8. As the owner, I want to choose how many Listings each Provider returns (default 50), so that I can trade breadth for speed and request volume.
9. As the owner, I want to pass Provider-specific extras, such as a Leboncoin category, so that I can use filters the shared Filter set leaves out.
10. As the owner, I want to paste a Native URL copied from a Provider's website, so that a complex search I built in the site's own UI runs as-is.
11. As the owner, I want a Native URL to go only to the Provider it belongs to, so that it is never misapplied elsewhere.
12. As the owner, I want the response to tell me which Filters each Provider applied natively and which bonneaffaire applied locally, so that I understand why results may differ from the site.
13. As the owner, I want Filters a Provider can't handle natively applied to its fetched Listings, so that the merged results are consistent.

### Listing shape

14. As the owner, I want every Listing to show its Provider, title, Price, Condition, Seller kind, thumbnail and link, so that I can scan and click through.
15. As the owner, I want Price in integer cents with an explicit currency, so that comparisons are exact and never suffer from float or string errors.
16. As the owner, I want Shipping and Buyer fee shown separately from Price when the Provider states them, so that I know what each part costs.
17. As the owner, I want Total cost shown only when Price, Shipping and Buyer fee are all known, so that I'm never shown a misleading total.
18. As the owner, I want Vinted's buyer protection fee captured as a Buyer fee, so that Vinted Prices aren't misleadingly low next to other Providers.
19. As the owner, I want the Provider's original condition wording kept next to the canonical Condition, so that I can check how it was mapped.
20. As the owner, I want refurbished items to carry Condition Refurbished, so that warranted refurbished goods aren't mixed with private used sales.
21. As the owner, I want Seller kind (Private, Professional, Unknown) on each Listing, so that I can judge warranty and reliability.
22. As the owner, I want Listings from Providers in other countries to keep their own currency, unconverted, so that no hidden exchange rate distorts the Prices.
23. As the owner, I want each Listing identified by Provider plus the Provider's own ID, so that I and my agents can refer back to it unambiguously.
24. As the owner, I want the same item cross-posted on two Providers to appear as two Listings, so that bonneaffaire never wrongly merges different items.

### Listing details

25. As the owner, I want to fetch full details for one Listing (description, all photos, seller information, attributes), so that I can evaluate it without opening the site.
26. As the owner, I want a Search to return summaries only, so that a Search doesn't multiply requests and get me blocked.
27. As the owner, I want fetching details for a Listing that no longer exists to say so clearly, so that I know it's gone rather than broken.

### Partial failure and outcomes

28. As the owner, I want a Search to succeed when one Provider fails, so that a Leboncoin block doesn't cost me the other Providers' results.
29. As the owner, I want each Provider's outcome (ok, blocked, timed out, failed) reported with every Search, so that an empty result is never ambiguous.
30. As an agent, I want Provider outcomes in machine-readable form, so that I can decide whether to retry, wait, or tell the user.
31. As the owner, I want a blocked Provider to back off rather than retry immediately, so that a temporary block doesn't become a ban on my home IP.
32. As the owner, I want a response with an unexpected shape reported as a failure rather than silently returning nothing, so that I notice when a Provider changes its site.

### Politeness and safety

33. As the owner, I want all Provider access to be anonymous, so that my personal Vinted, Leboncoin or eBay accounts are never at risk.
34. As the owner, I want requests throttled per Provider, so that my residential IP stays under anti-bot thresholds.
35. As the owner, I want identical Searches repeated within a short window answered from cache, so that agents asking the same question don't multiply requests.
36. As the owner, I want each Provider enabled or disabled in configuration, so that I can switch off one that is misbehaving without redeploying code.

### Agents (MCP)

37. As an agent, I want a search tool over MCP that accepts keywords, Filters, Provider selection, a per-Provider limit or a Native URL, so that I can search the market for the user.
38. As an agent, I want a tool to fetch one Listing's details, so that I can look closer at promising results.
39. As an agent, I want a tool that lists available Providers and what each supports (native Filters, Native URLs, Listing details), so that I can build valid requests.
40. As an agent, I want compact, consistent JSON results, so that I can reason over many Listings without wasting context.
41. As an agent running on another machine, I want to reach the MCP server over Streamable HTTP through Cloudflare Access using a service token, so that I can use it when I'm away from home.

### CLI

42. As the owner, I want a CLI command to search with the same options as the MCP tool, so that I can use it from a terminal or scripts.
43. As the owner, I want readable table output by default and JSON on request, so that the CLI serves both humans and scripts.
44. As the owner, I want a CLI command to fetch one Listing's details, so that I can inspect a result quickly.
45. As the owner, I want a CLI command to list Providers and their capabilities, so that I know what's available.

### Deployment

46. As the owner, I want bonneaffaire packaged as a Docker Compose service for Synology Container Manager on my DS920+, so that it runs permanently from my residential IP.
47. As the owner, I want it exposed outside my home only through a Cloudflare Tunnel behind Cloudflare Access, so that strangers can't make my IP scrape on their behalf.
48. As the owner, I want configuration (enabled Providers, eBay credentials, throttle rates, cache duration, default limit) in environment variables or a config file, so that I can change settings without rebuilding.

### Extensibility

49. As the developer, I want to add a Provider by writing one module that implements the Provider interface, so that new Providers don't require changes to the core.
50. As the developer, I want each Provider to declare its capabilities, so that the core and the agent-facing tools adapt automatically.
51. As the developer, I want Amazon and Back Market to fit the same interface as best-effort Providers in v1.1, so that adding them needs no redesign.
52. As the developer, I want a config-driven generic Provider for simple retail sites (search-page selectors plus JSON-LD product pages), so that the long tail of retailers is cheap to add. LDLC is its first user.

## Implementation Decisions

- **Language:** Python end-to-end (ADR-0001). Modern Python packaged with uv. Typed models for requests, Listings and outcomes.
- **Core module:** the core library is the single entry point, offering:
  - **Search:** takes a request containing either (a) keywords plus Filters, Provider selection, per-Provider limit and Provider-specific extras, or (b) a Native URL. It returns merged Listings, a Provider outcome per Provider asked, and a per-Provider record of which Filters were applied natively and which locally.
  - **Get Listing:** takes Provider plus Provider ID (or a Listing URL) and returns full details.
  - **List Providers:** returns each Provider and its capabilities.

  The core owns fan-out (concurrent, with a per-Provider timeout), local Filter application, merging, sorting after merging, caching and throttling. It never paginates across Providers.
- **Provider interface:** a Python Protocol.
  - Searching is required.
  - Listing details are optional, declared as a capability.
  - Each Provider declares which canonical Filters it handles natively, whether it accepts Native URLs and how to recognise its own URLs, and which Provider-specific extras it accepts.
  - Each Provider instance has a country setting. v1 runs in France.
  - Providers signal outcomes through typed exceptions or results: blocked, timed out, unexpected shape, not found. The core converts these into Provider outcomes and never raises them to the caller for a multi-Provider Search.
- **Listing model:**
  - Provider and Provider ID together are the identity.
  - Fields: title, URL, thumbnail; Price as integer cents plus ISO currency; optional Shipping, optional Buyer fee, and Total cost computed only when all three are known.
  - Condition from {New, Refurbished, LikeNew, Used, ForParts, Unknown}, plus the raw Provider label. Seller kind from {Private, Professional, Unknown}.
  - Optional location and posting time.
  - Raw Provider attributes kept, so later phases such as Product matching can use them.
  - A Listing is one offer. On retailers, Search returns the offer shown on the search page, and Get Listing can return other offers for the same product as separate Listings.
- **Listing details:** extend the Listing with description, all photo URLs, seller information and attributes.
- **Providers in v1:**
  - **Leboncoin:** wraps the maintained `lbc` library (curl_cffi impersonation). Supports location and radius, category as an extra, and Native URLs.
  - **Vinted:** wraps a maintained Vinted library that already uses the new `svc-catalogue` endpoint (`vinted_scraper` or `vinted-api-kit`; pick the healthier one at implementation time). Anonymous session. Buyer fee captured. Native URLs supported.
  - **eBay:** our own small client for the official Browse API with OAuth client credentials, marketplace EBAY_FR. Condition mapped from eBay condition IDs. Requires the owner to create eBay developer credentials.
  - **LDLC:** the first instance of the config-driven generic retail Provider. Plain HTTP; search-page cards parsed from HTML; details from JSON-LD Product/Offer. Condition is New and Seller kind is Professional.
- **Library policy:** wrap upstream libraries behind our Provider interface. Replace a library with our own client only if it goes stale.
- **v1.1 Providers (not built in v1, but the interface must accommodate them):**
  - **Amazon.fr:** best-effort scraping of search HTML, featured offer only. The Creators API is unavailable without affiliate sales.
  - **Back Market:** best-effort. Try curl_cffi impersonation first. Add a browser-based fetcher (camoufox) only if impersonation fails.
- **Politeness:** anonymous access only, never logged in. Throttling per Provider, with configurable rates. Short cache keyed on the normalised request. Typed handling of blocks: a blocked Provider backs off rather than retrying immediately.
- **Interfaces:**
  - **MCP server** over Streamable HTTP, with tools for Search, Get Listing and List Providers, returning compact JSON.
  - **CLI** with the same three operations, table output by default and JSON output on request.
  - Both are thin adapters over the core. An HTTP JSON API is deferred.
- **Deployment:** Docker image for x86-64 (DS920+), Docker Compose on Synology Container Manager. External access only through a Cloudflare Tunnel with Cloudflare Access. Agents authenticate with an Access service token. The app itself has no authentication, and LAN access is open (accepted). No proxy service; egress is the home residential IP.
- **Configuration:** enabled Providers, per-Provider throttle and timeout, default per-Provider limit (50), cache duration, eBay credentials.

## Testing Decisions

- **What makes a good test:** it exercises external behaviour through the public seams below and asserts on returned Listings, Provider outcomes and Filter reports. It never asserts on internal calls or private structure. A refactor that keeps behaviour unchanged must not break tests.
- **Seam 1, the core search API with fake Providers.** This is the main seam. Tests call Search, Get Listing and List Providers on the core with fake Providers registered. They cover:
  - fan-out and the per-Provider limit
  - merging and sorting after merging
  - native vs local Filter application and the Filter report
  - Native URLs routed to the right Provider only
  - Provider outcomes for blocked, timed-out, failed and unexpected-shape Providers, with partial results preserved
  - cache hits for repeated requests, throttling behaviour, and backoff after a block
  - Total cost computed only when all its parts are known
- **Seam 2, each real Provider against recorded responses.** Each Provider is fed saved real responses from fixture files: Leboncoin and Vinted JSON, eBay Browse JSON, LDLC search HTML and product JSON-LD. Tests assert on the Listings produced:
  - Price in cents and currency, Shipping and Buyer fee
  - Condition mapping including raw labels, Seller kind
  - Native URL parsing, details parsing
  - how block responses and unexpected shapes are reported

  For wrapped libraries, the recorded response is injected into the library's HTTP client. Fixtures are refreshed when a Provider changes its site.
- **MCP and CLI:** one smoke test each, confirming the adapter calls the core and serialises results. Behaviour is covered at Seam 1.
- **Live canary tests:** a separately marked suite that hits each real Provider with a simple Search and checks the response still parses. It is excluded from the default test run and run manually or weekly, to catch endpoint changes like Vinted's October 2026 search endpoint switch.
- **Prior art:** none in this repo yet. The replay-transport testing and live canary approach follows vinted-bot (see the prior-art research report).

## Out of Scope

- Monitoring: saved searches run on a schedule, price history, delisting events, alerts and notifications.
- Product matching: grouping Listings under a canonical product, price per TB, EAN or model-number matching.
- Removing duplicate Listings cross-posted on several Providers.
- Amazon and Back Market (v1.1), and a browser-based fetcher.
- Sold-price data, from any Provider.
- Any logged-in or account-based action: messaging, buying, favouriting.
- Currency conversion.
- Countries other than France (the country setting exists, but only France is configured and tested).
- An HTTP JSON API, OAuth for claude.ai custom connectors, and multi-user support.
- Proxy services and residential proxy rotation.
- A canonical category taxonomy.

## Further Notes

- Glossary terms (Provider, Listing, Search, Filter, Native URL, Provider outcome, Condition, Price, Shipping, Buyer fee, Total cost, Seller kind) are defined in GLOSSARY.md. Use them consistently in code and output.
- Research backing these decisions is in the provider ecosystem, prior art and retailer access reports under the research docs. ADR-0001 records the choice of Python over Rust.
- Vinted's and Leboncoin's terms of service forbid automated access. This tool is for private use at low request rates, and its politeness rules exist to keep that footprint small.
- The internal endpoints change often. Expect regular fixture refreshes and occasional library upgrades; the live canary suite is the early warning.
- Owner action required before the eBay Provider can work: create an eBay developer account and production keys. If production Browse access is delayed (the eBay limits page mentions an additional licence for Buy APIs), ship the other three v1 Providers first.
- Q27 and Q28 from the design session (v1/v1.1 split, deferring the browser fetcher) were accepted together with the test seams.
