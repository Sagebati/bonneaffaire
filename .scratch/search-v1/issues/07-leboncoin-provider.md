# 07: Leboncoin Provider

**What to build:** Leboncoin as a Provider, wrapping the maintained `lbc` library. It supports:
- Search: keywords, price range, location or radius applied natively, and category as a Provider-specific extra
- Native URLs from leboncoin.fr
- Listing details

Listings carry Seller kind (Private or Professional), Shipping where offered, location, and Condition mapped from Leboncoin's labels with the raw label kept. A DataDome block is reported as the outcome blocked. Access is anonymous only. See `docs/research/` for endpoints.

**Blocked by:** 02, 03, 04, 05

**Status:** ready-for-agent

- [ ] A keyword Search, a Filtered Search, and a pasted Leboncoin URL all return Leboncoin Listings via the CLI
- [ ] Listing details work for a Leboncoin Listing
- [ ] Condition, Seller kind, Price in cents, Shipping and location are mapped correctly in fixture tests built from recorded responses injected into the library's HTTP client
- [ ] A recorded DataDome 403 produces outcome blocked
- [ ] A live canary test for Leboncoin exists, excluded from the default run
