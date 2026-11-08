# bonneaffaire

Search second-hand and retail marketplaces in one place, from a terminal or from an AI agent.

One Search runs across **Vinted, Leboncoin, eBay and LDLC** at once and returns Listings in a single shape: Price in cents with currency, Shipping and Buyer fee when they're known, a common Condition, and the kind of seller. Each Provider reports what happened when it was asked, so "no results" is never confused with "blocked".

The motivating use case is knowing what something really costs on the French market, new and used, for example hard disks.

> **Private use.** bonneaffaire is meant for personal use at low request rates. Vinted's and Leboncoin's terms of service forbid automated access. bonneaffaire never logs into an account; it throttles every Provider, caches repeated Searches, and backs off when it's blocked. You are responsible for how you use it.

## Features

- **One Search, many Providers**, asked concurrently. Results are merged and can be sorted by price or recency.
- **Filters** for price range, Condition, location and sort. Providers apply what they support natively; bonneaffaire applies the rest locally and tells you which was which.
- **Native URLs**: paste a search URL copied from a Provider's website, and it runs as-is on that Provider.
- **Listing details**: description, photos, seller, availability and Total cost for a single Listing.
- **Partial results**: when one Provider is blocked or times out, you still get the others, with a status for each.
- **Politeness**: a request rate per Provider, a short cache, and backoff after a block.
- **Two interfaces** over the same core: a CLI, and an MCP server for agents.
- **Built to run at home**: a Docker image for a NAS, reachable from outside through Cloudflare Tunnel and Access.

## Providers

| Provider | Access | Native Filters | Native URLs | Listing details |
| --- | --- | --- | --- | --- |
| `vinted` | vinted.fr through [`vinted_scraper`](https://github.com/Giglium/vinted_scraper), anonymous | price, condition, sort | yes | yes |
| `leboncoin` | leboncoin.fr through [`lbc`](https://github.com/etienne-hd/lbc), anonymous | price, location, sort (extra: `category`) | yes | yes |
| `ebay` | the official [Browse API](https://developer.ebay.com/api-docs/buy/browse/overview.html) on EBAY_FR; needs your developer keys | price, condition, sort | no | yes |
| `ldlc` | ldlc.com, HTML search pages plus JSON-LD product pages | none (filtered locally) | yes | yes |

eBay stays disabled until you set `BONNEAFFAIRE_EBAY_CLIENT_ID` and `BONNEAFFAIRE_EBAY_CLIENT_SECRET`. Amazon and Back Market are planned as best-effort Providers.

## Quick start

You need Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Sagebati/bonneaffaire.git
cd bonneaffaire
uv sync
```

Search every enabled Provider:

```bash
uv run bonneaffaire search disque dur 8 To
```

Used disks under €150 on Vinted and Leboncoin, cheapest first, as JSON:

```bash
uv run bonneaffaire search disque dur 8 To -p vinted -p leboncoin --condition Used --condition LikeNew --max-price 150 --sort price --json
```

Run a search you built on the Provider's website:

```bash
uv run bonneaffaire search "https://www.leboncoin.fr/recherche?text=disque+dur+8+to"
```

Get one Listing's details, by URL or by Provider and ID:

```bash
uv run bonneaffaire listing https://www.ldlc.com/fiche/PB00281525.html
```

```bash
uv run bonneaffaire listing vinted 10718798068
```

See which Providers are available and what each supports:

```bash
uv run bonneaffaire providers
```

## Using it from an agent (MCP)

bonneaffaire includes an MCP server that uses the Streamable HTTP transport:

```bash
uv run bonneaffaire serve --host 127.0.0.1 --port 8000
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`, and a health check answers at `/health`. To add it to Claude Code:

```bash
claude mcp add --transport http bonneaffaire http://127.0.0.1:8000/mcp
```

The server exposes three tools: `search`, `get_listing` and `list_providers`. [docs/api.md](docs/api.md) describes their parameters and responses, along with the CLI and the Python core.

## Configuration

All settings are environment variables. [.env.example](.env.example) lists every one, with comments.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BONNEAFFAIRE_DISABLED_PROVIDERS` | empty | Providers to switch off, e.g. `vinted,ebay` |
| `BONNEAFFAIRE_DEFAULT_LIMIT` | `50` | Listings per Provider when a Search gives no limit |
| `BONNEAFFAIRE_TIMEOUT_SECONDS` | `20` | Seconds each Provider gets to answer |
| `BONNEAFFAIRE_PROVIDER_TIMEOUTS` | empty | Per-Provider overrides, e.g. `leboncoin=30` |
| `BONNEAFFAIRE_RATE_PER_MINUTE` | `20` | Requests per minute to each Provider |
| `BONNEAFFAIRE_PROVIDER_RATES` | empty | Per-Provider overrides, e.g. `leboncoin=5` |
| `BONNEAFFAIRE_CACHE_SECONDS` | `120` | How long a repeated identical Search is served from cache |
| `BONNEAFFAIRE_BACKOFF_SECONDS` | `600` | How long a blocked Provider is left alone |
| `BONNEAFFAIRE_EBAY_CLIENT_ID` / `_SECRET` | empty | eBay developer keys; eBay is disabled without them |
| `BONNEAFFAIRE_HOST` / `BONNEAFFAIRE_PORT` | `127.0.0.1` / `8000` | Where `serve` listens |

The cache and the backoff live in memory, so they only help inside a long-running process such as `serve`.

## Deployment

The repo includes a `Dockerfile` and a `compose.yaml` that run bonneaffaire next to a `cloudflared` container. Run it from a residential connection: Vinted and Leboncoin reject datacenter IPs. [docs/deployment.md](docs/deployment.md) walks through setting it up on a Synology NAS, the Cloudflare Tunnel and the Access service token, and configuring an agent to send the Access headers.

```bash
cp .env.example .env
```

```bash
docker compose up -d
```

## Development

The rules are in [CLAUDE.md](CLAUDE.md). All four checks must pass before every commit:

```bash
uv run ruff check
```

```bash
uv run ruff format --check
```

```bash
uv run ty check
```

```bash
uv run pytest
```

Tests come in two kinds:

- **Core tests** call the core with fake Providers. They cover fan-out, merging, Filters, outcomes, cache, throttle and backoff.
- **Provider tests** feed real recorded responses into each Provider and check the Listings it produces. The fixtures live under `tests/fixtures/`; seller names and IDs in them are anonymised.

**Live canaries** hit the real sites. They are excluded by default, so run them by hand now and then to catch a Provider changing its site:

```bash
uv run pytest -m canary
```

### Adding a Provider

A Provider is a module in `src/bonneaffaire/providers/` that implements the `Provider` protocol from `providers/__init__.py`:

- a `name`, a `country` and `capabilities` (the native Filters, Native URL support, Listing details and extras it supports)
- `async search(query, limit) -> list[Listing]`
- optionally, `get_listing` and `listing_id_from_url` for Listing details, and `recognises_native_url` for Native URLs

It reports trouble by raising `ProviderBlocked`, `ProviderTimeout`, `UnexpectedShape` or `ListingNotFound`. The core turns these into Provider outcomes. To make the Provider available, register it in `registry.py`. `list_providers` and the CLI pick it up automatically.

A simple retail site that has HTML search pages and JSON-LD product pages doesn't need code. Describe it with a `RetailProviderConfig`, as `providers/ldlc.py` does.

## Project documents

- [GLOSSARY.md](GLOSSARY.md): the domain vocabulary (Provider, Listing, Search, Filter, Condition, Buyer fee, and so on). The code and output use these terms.
- [docs/api.md](docs/api.md): the CLI, MCP and Python API reference.
- [docs/deployment.md](docs/deployment.md): running it on a NAS behind Cloudflare.
- [docs/adr/](docs/adr/): architecture decisions, such as why Python and not Rust.
- [docs/research/](docs/research/): how each marketplace can be accessed, and prior art.
- [.scratch/search-v1/](.scratch/search-v1/): the spec and tickets for this version.

## Roadmap

- **Monitoring**: saved Searches that run on a schedule, with price history and delisting events.
- **Product matching**: group Listings under a canonical product, for example to get price per TB for disks.
- **More Providers**: Amazon and Back Market (best-effort), plus more retailers through the config-driven retail Provider.
