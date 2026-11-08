# 09: eBay Provider

**What to build:** eBay as a Provider through the official Browse API, marketplace EBAY_FR, with our own small client using OAuth client credentials. It supports Search (keywords, price range, Condition, and sort, all native) and Listing details. eBay condition IDs map to Condition, with the raw value kept. Shipping comes from the API response, and Seller kind comes from the seller account type where exposed. Credentials come from configuration. With no credentials configured, the Provider is disabled with a clear message.

Owner action: create an eBay developer account and production keys.

**Blocked by:** 02, 03, 05

**Status:** ready-for-human

- [ ] With credentials configured, a keyword Search and a Filtered Search return eBay Listings via the CLI (passes against doc-sample fixtures; live check waits for the owner's credentials)
- [ ] Listing details work for an eBay Listing (passes against fixtures, by Provider ID and by URL; live check waits for credentials)
- [x] Condition ID mapping, Price in cents, Shipping and Seller kind are correct in fixture tests built from recorded Browse API JSON
- [x] The OAuth token is obtained and refreshed transparently
- [x] Rate-limit and auth errors produce clear Provider outcomes
- [x] Without credentials, eBay is reported as disabled rather than failing every Search
- [x] A live canary test for eBay exists, excluded from the default run

## Comments

Implemented and merged on `search-v1`. The two unticked criteria need real eBay credentials (`BONNEAFFAIRE_EBAY_CLIENT_ID` / `BONNEAFFAIRE_EBAY_CLIENT_SECRET`): owner to create keys, then run `uv run pytest -m canary -k ebay` and a CLI Search to verify and close.
