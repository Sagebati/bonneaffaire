# 02: Search across several Providers, with Provider outcomes

**What to build:** A Search runs against all enabled Providers, or a chosen subset, concurrently. Each Provider fetches up to a per-Provider limit (default 50, configurable per request). Results are merged into one list and sorted after merging, by Price or by recency, with no cross-Provider pagination. Every Search reports a Provider outcome for each Provider asked: ok, blocked, timed out, or failed, where failed includes an unexpected response shape. Partial results are always kept. The CLI shows the Provider outcomes alongside the Listings.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A Search can target all enabled Providers or an explicit subset
- [ ] Providers are queried concurrently, with a per-Provider timeout
- [ ] Each Provider returns at most the per-Provider limit; the default is 50
- [ ] Merged results sort correctly by Price and by recency across Providers
- [ ] When one fake Provider raises blocked, times out, fails, or returns an unexpected shape, the Search still returns the other Providers' Listings and reports the correct outcome for each Provider
- [ ] An empty result from a healthy Provider is reported as ok with zero Listings, which is distinct from blocked or failed
- [ ] Providers can be enabled or disabled in configuration
- [ ] Tested at the core Search seam with fake Providers
