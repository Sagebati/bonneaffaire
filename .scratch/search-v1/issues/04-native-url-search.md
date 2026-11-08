# 04: Native URL Search

**What to build:** Instead of keywords and Filters, a Search can be given a Native URL: a search page address copied from a Provider's website. The core asks each Provider whether it recognises the URL and sends the Search only to that Provider, which runs the search as the URL describes. Proven end to end with LDLC search URLs. A URL that no Provider recognises produces a clear error.

**Blocked by:** 01

**Status:** resolved

- [x] Providers declare whether they accept Native URLs and how to recognise their own
- [x] Pasting an LDLC search URL into the CLI returns the same Listings as the equivalent keyword Search
- [x] A Native URL is routed only to the Provider that recognises it
- [x] An unrecognised URL returns a clear error naming the problem
- [x] Tested at the core seam with fake Providers, plus an LDLC fixture test for URL parsing
