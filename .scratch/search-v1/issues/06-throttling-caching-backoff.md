# 06: Throttling, caching and backoff

**What to build:** Polite behaviour, so the home residential IP stays under anti-bot thresholds:
- Requests to each Provider are throttled at a configurable rate.
- Identical Searches (same normalised request) within a short, configurable window are answered from cache.
- After a Provider reports blocked, it backs off for a period instead of being hit again immediately. During that time it reports blocked without making requests.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Concurrent Searches never exceed a Provider's configured request rate
- [ ] A repeated identical Search within the cache window makes no Provider requests and returns the same result
- [ ] The cache window and per-Provider rates are configurable
- [ ] After a blocked outcome, the next Searches skip that Provider until the backoff expires, and report blocked meanwhile
- [ ] Tested at the core seam with fake Providers and a controllable clock
