# 01: Tracer bullet: Search LDLC from the CLI

**What to build:** The thinnest complete path through bonneaffaire. Running a CLI search command with keywords (e.g. "disque dur 8 To") performs a Search against LDLC and prints the resulting Listings as a readable table, or as JSON on request. This ticket establishes:
- the Python project, managed with uv (see ADR-0001)
- the Listing model: Provider plus Provider ID as identity; title, URL, thumbnail; Price in integer cents with currency; optional Shipping, Buyer fee, and Total cost (computed only when all three are known); Condition plus the raw label; Seller kind; raw attributes
- the Provider Protocol, with capability declarations
- a core Search that, for now, handles a single Provider
- the config-driven generic retail Provider (search-page card selectors plus JSON-LD product data), configured for LDLC: Condition New, Seller kind Professional
- the testing conventions for recorded-response fixture tests and for a live canary suite that is excluded from the default test run

See spec: `.scratch/search-v1/spec.md`. Use GLOSSARY.md terms.

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] A CLI search command with keywords returns LDLC Listings, as a table by default and as JSON with a flag
- [x] Each Listing has Provider, Provider ID, title, URL, thumbnail, Price in integer cents plus currency, Condition (New) with the raw label, and Seller kind (Professional)
- [x] Total cost is present only when Price, Shipping and Buyer fee are all known
- [x] LDLC is defined through the generic retail Provider's configuration, not as a hand-written LDLC class
- [x] A fixture test feeds recorded LDLC search HTML to the Provider and asserts on the Listings produced
- [x] A live canary test for LDLC exists and does not run in the default test run
- [x] The default test run passes
