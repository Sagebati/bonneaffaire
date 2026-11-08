# 08: Vinted Provider

**What to build:** Vinted (vinted.fr) as a Provider, wrapping whichever of `vinted_scraper` and `vinted-api-kit` is healthier at implementation time. Both use the new `svc-catalogue` endpoint that replaced the old one in October 2026. It uses an anonymous session and supports:
- Search: keywords, price range, Condition, sort
- Native URLs from vinted.fr
- Listing details

Vinted's buyer protection is captured as a Buyer fee, so Total cost is computed when Shipping is known. Vinted's condition labels map to Condition, with the raw label kept. Seller kind distinguishes Vinted Pro sellers. The country setting defaults to France.

**Blocked by:** 02, 03, 04, 05

**Status:** ready-for-agent

- [ ] A keyword Search, a Filtered Search, and a pasted Vinted URL all return Vinted Listings via the CLI
- [ ] Listing details work for a Vinted Listing
- [ ] Buyer fee, Price in cents, Condition mapping (e.g. "Neuf avec étiquette", "Très bon état") and Seller kind are correct in fixture tests built from recorded responses
- [ ] Blocked responses (403 from Cloudflare or DataDome) produce outcome blocked; an unexpected shape produces failed
- [ ] The chosen library and the reason for choosing it are noted in the ticket's comments
- [ ] A live canary test for Vinted exists, excluded from the default run
