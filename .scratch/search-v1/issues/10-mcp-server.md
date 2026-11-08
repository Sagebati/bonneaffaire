# 10: MCP server

**What to build:** An MCP server over Streamable HTTP, a thin adapter over the core, with three tools:
- **Search:** keywords plus Filters, Provider selection, per-Provider limit and extras, or a Native URL
- **Get Listing**
- **List Providers:** each Provider and its capabilities (native Filters, Native URL support, Listing details, enabled/disabled)

Results are compact, consistent JSON, including Provider outcomes and the Filter report. The CLI gets a matching providers command. The app itself has no authentication (Cloudflare Access protects external access).

**Blocked by:** 02, 03, 04, 05

**Status:** ready-for-agent

- [ ] An MCP client can call Search, Get Listing and List Providers over Streamable HTTP
- [ ] Tool input schemas describe Filters, Condition values, Provider names and Native URL clearly enough for an agent to build valid requests
- [ ] Search results include Listings, Provider outcomes and the Filter report as compact JSON
- [ ] The CLI providers command shows the same capability information
- [ ] One smoke test confirms the adapter calls the core and serialises results
