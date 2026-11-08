# 05: Listing details

**What to build:** Get Listing in the core, plus a CLI command to use it. Given Provider plus Provider ID, or a Listing URL, it returns full details: everything in a Listing plus description, all photo URLs, seller information and attributes. Implemented for LDLC from the JSON-LD on its product pages. A Listing that no longer exists is reported as not found, distinct from a failure. Providers declare whether they support Listing details. On retailers, other offers for the same product may come back as additional Listings.

**Blocked by:** 01

**Status:** ready-for-agent

- [x] The CLI command fetches details for an LDLC Listing, by Provider plus ID and by URL
- [x] Details include description, photos, attributes (e.g. EAN) and availability where the Provider exposes them
- [x] A removed Listing returns not found, not a generic failure
- [x] Asking for details from a Provider without that capability returns a clear "unsupported" result
- [x] Fixture test against a recorded LDLC product page; core-seam test for not found and unsupported
