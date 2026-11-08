# API reference

bonneaffaire has one core and two interfaces over it: an **MCP server** for agents and a **CLI** for people and scripts. Both take the same requests and return the same data. The words used here (Provider, Listing, Filter, Native URL, Provider outcome, Condition, Buyer fee, Total cost) are defined in [GLOSSARY.md](../GLOSSARY.md).

## MCP server

```bash
uv run bonneaffaire serve --host 0.0.0.0 --port 8000
```

- **Transport:** Streamable HTTP
- **MCP endpoint:** `http://HOST:PORT/mcp`
- **Health check:** `GET /health` returns `{"status": "ok", "enabled_providers": [...]}`. It never contacts a Provider.
- **Auth:** none in the app. Expose it outside your LAN only behind Cloudflare Access; see [deployment.md](deployment.md).

Responses are compact JSON, returned both as text and as structured content. Null and empty fields are left out, except in `list_providers`. A malformed request, such as an unknown Provider, both keywords and a Native URL, or Filters combined with a Native URL, comes back as a tool error.

### `search`

Searches for Listings across Providers, either by keywords plus Filters or by a Native URL.

| Parameter | Type | Notes |
| --- | --- | --- |
| `keywords` | string | What to look for, e.g. `"disque dur 8 To"`. Give either this or `native_url`. |
| `native_url` | string | A search page URL copied from a Provider's website. It goes only to the Provider that recognises it, and takes no Filters or extras. |
| `providers` | string[] | Provider names to ask. Leave it out to ask every enabled Provider. |
| `limit` | int > 0 | Maximum Listings per Provider. Defaults to `BONNEAFFAIRE_DEFAULT_LIMIT`, which is 50. |
| `price_min`, `price_max` | `{"cents": int, "currency": "EUR"}` | Price range on the item Price, which excludes Shipping and fees. |
| `conditions` | Condition[] | Keep Listings in any of these Conditions: `New`, `Refurbished`, `LikeNew`, `Used`, `ForParts`, `Unknown`. |
| `location` | `{"place": str, "radius_km": int?}` | A city or postcode. Only Providers that support location natively can apply it. |
| `sort` | `"price"` or `"recency"` | Sorts the merged Listings. With recency, Listings that have no posting time (Vinted, LDLC) come last. |
| `extras` | `{provider: {name: value}}` | Provider-specific extras, e.g. `{"leboncoin": {"category": "informatique"}}`. |

The response has three parts:

```jsonc
{
  "listings": [
    {
      "provider": "vinted",
      "provider_id": "10718798068",
      "title": "Disque dur WD Red 8 To",
      "url": "https://www.vinted.fr/items/10718798068-...",
      "thumbnail": "https://images1.vinted.net/...",
      "price": {"cents": 9000, "currency": "EUR"},
      "buyer_fee": {"cents": 520, "currency": "EUR"},   // when the Provider states it
      "shipping": {"cents": 499, "currency": "EUR"},    // when the Provider states it
      "total_cost": {"cents": 10019, "currency": "EUR"},// only when price, shipping and buyer_fee are all known
      "condition": "LikeNew",
      "condition_label": "Très bon état",               // the Provider's own wording
      "seller_kind": "Private",                         // Private | Professional | Unknown
      "location": "Lyon",
      "posted_at": "2026-11-07T18:21:00Z",
      "attributes": { }                                 // raw Provider data
    }
  ],
  "outcomes": [
    {"provider": "vinted", "status": "ok", "listing_count": 48},
    {"provider": "leboncoin", "status": "blocked", "message": "DataDome challenge (HTTP 403)"}
  ],
  "filter_reports": [
    {"provider": "vinted", "native": ["price_max", "condition"], "local": []},
    {"provider": "ldlc", "local": ["price_max", "condition"]}
  ]
}
```

- **`outcomes`** gives one entry per Provider asked. `status` is `ok`, `blocked`, `timed_out` or `failed`. An `ok` Provider with zero Listings genuinely found nothing; a `blocked` one couldn't look.
- **`filter_reports`** gives one entry per Provider:
  - `native`: the Filters the Provider applied itself.
  - `local`: the Filters bonneaffaire applied to the Provider's Listings.
  - `unapplied`: the Filters nobody could apply, for example location on a Provider that has no location data.
  - `ignored_extras`: extras the Provider doesn't accept.

### `get_listing`

Gets one Listing's full details. Identify the Listing with **either** `provider` plus `provider_id`, as Search returned them, **or** `url`.

The response is `{"status": ..., "provider": ..., "listing": ..., "message": ...}`. `status` is one of:
- `ok`: `listing` holds the details.
- `not_found`: the Listing is gone.
- `unsupported`: the Provider can't fetch details, or it's an unknown Provider or URL.
- `blocked`, `timed_out` or `failed`.

On top of the Listing fields above, `listing` adds:
- `description`
- `photos`, a list of URLs
- `seller` (`name`, `url`)
- `availability`, e.g. schema.org `InStock`
- `other_offers`: other offers for the same product, on retailers

### `list_providers`

Takes no parameters and returns `{"providers": [...]}`. Each entry has:

```json
{
  "name": "leboncoin",
  "country": "FR",
  "enabled": true,
  "native_filters": ["price_min", "price_max", "location", "sort"],
  "native_urls": true,
  "listing_details": true,
  "extras": ["category"],
  "disabled_reason": null
}
```

Disabled Providers are listed too. `disabled_reason` says why, for example when eBay's keys are missing.

### Connecting an agent

Claude Code on the same machine or LAN:

```bash
claude mcp add --transport http bonneaffaire http://nas.local:8000/mcp
```

From outside, through Cloudflare Access, the agent must send the service-token headers `CF-Access-Client-Id` and `CF-Access-Client-Secret`. [deployment.md](deployment.md) has a complete example.

## CLI

Every command accepts `--json`, which prints the same JSON the MCP tools return. Without it, the output is a readable table.

### `bonneaffaire search KEYWORDS... [options]`

KEYWORDS can also be a single Native URL.

| Option | Meaning |
| --- | --- |
| `-p, --provider NAME` | Ask only this Provider. Repeatable. |
| `--limit N` | Maximum Listings per Provider. |
| `--min-price EUR`, `--max-price EUR` | Price range in euros, e.g. `99.90`. |
| `--condition C` | An accepted Condition. Repeatable. |
| `--near PLACE`, `--radius-km N` | Search around a place. |
| `--sort price\|recency` | Order of the merged Listings. |
| `--extra provider.name=value` | A Provider-specific extra. Repeatable. |
| `--json` | Print JSON. |

The command exits with 1 for a Native URL that no Provider recognises, and with 2 for an unknown Provider.

### `bonneaffaire listing TARGET [PROVIDER_ID]`

TARGET is either a Listing URL, or a Provider name followed by the Provider ID. The command exits with 1 when the status isn't `ok`.

### `bonneaffaire providers`

Lists the Providers and their capabilities.

### `bonneaffaire serve [--host H] [--port P]`

Runs the MCP server. `BONNEAFFAIRE_HOST` and `BONNEAFFAIRE_PORT` set the defaults.

## Python core

The CLI and the MCP server are thin adapters over `bonneaffaire.core.Bonneaffaire`:

```python
import asyncio
from bonneaffaire.models import Condition, Money, SearchQuery, SearchRequest, Sort
from bonneaffaire.registry import default_core

async def main() -> None:
    core = default_core()  # Providers and settings from the environment
    result = await core.search(
        SearchRequest(
            query=SearchQuery.build(
                keywords="disque dur 8 To",
                price_max=Money(cents=15000, currency="EUR"),
                conditions=frozenset({Condition.USED, Condition.LIKE_NEW}),
                sort=Sort.PRICE,
            ),
            providers=frozenset({"vinted", "leboncoin"}),
        )
    )
    for listing in result.listings:
        print(listing.provider, listing.price.cents / 100, listing.title)

asyncio.run(main())
```

- `core.search(SearchRequest) -> SearchResult` never raises because of a Provider; failures show up in `outcomes`. It raises only for bad requests: `UnknownProvider` and `UnrecognisedNativeUrl`.
- `core.get_listing(ListingRequest) -> ListingResult` never raises.
- `core.list_providers() -> list[ProviderInfo]`.
