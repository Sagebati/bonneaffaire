# 03: Filters

**What to build:** Searches accept the canonical Filters: keywords, minimum and maximum Price, Condition (one or more of New, Refurbished, LikeNew, Used, ForParts), location or radius, and sort. Each Provider declares which Filters it handles natively; the core applies the rest locally to that Provider's fetched Listings. Every response reports, per Provider, which Filters were applied natively and which locally. Provider-specific extras (e.g. a category ID) pass through to the Provider that declares them. All of this is exposed as CLI options.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A price range and Condition Filter exclude non-matching Listings, whether the Provider applies them natively or the core applies them locally
- [ ] The response states, for each Provider, which Filters were applied natively and which locally
- [ ] A Filter that can't be applied at all, natively or locally (e.g. location on a Provider with no location data), is reported rather than silently ignored
- [ ] Provider-specific extras reach only the Provider that declares them
- [ ] CLI options exist for every canonical Filter and for extras
- [ ] Tested at the core Search seam with fake Providers that declare different native Filters
