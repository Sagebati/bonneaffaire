"""The MCP server: a thin adapter that exposes the core as three tools over Streamable HTTP.

There is no authentication: Cloudflare Access protects external access (see the spec).
"""

import json
from collections.abc import Callable
from typing import Annotated, Any

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, Field, ValidationError
from starlette.applications import Starlette

from bonneaffaire.core import Bonneaffaire, UnknownProvider, UnrecognisedNativeUrl
from bonneaffaire.models import (
    DEFAULT_LIMIT,
    Condition,
    ListingRequest,
    Location,
    Money,
    SearchQuery,
    SearchRequest,
    Sort,
)
from bonneaffaire.registry import default_core

INSTRUCTIONS = """\
bonneaffaire searches French second-hand and retail marketplaces (Providers) in one go.
Call list_providers to see which Providers exist and what each supports. Call search with
keywords and optional Filters, or with a Native URL copied from a Provider's website. Every
Search reports a Provider outcome per Provider asked (ok, blocked, timed_out, failed), so an
empty result is never ambiguous, and a Filter report saying which Filters each Provider applied
natively and which bonneaffaire applied locally. Prices are integer cents with a currency, never
converted. Call get_listing for one Listing's full details."""

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def compact(value: BaseModel | dict[str, Any]) -> CallToolResult:
    """A tool result as compact JSON text plus the same structured content.

    Null fields and empty collections are dropped, to save the agent's context.
    """
    data = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return json_result(_prune(data))


def json_result(data: dict[str, Any]) -> CallToolResult:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=data)


def _prune(value: Any) -> Any:
    if isinstance(value, dict):
        pruned = {key: _prune(item) for key, item in value.items()}
        return {key: item for key, item in pruned.items() if item not in (None, [], {})}
    if isinstance(value, list):
        return [_prune(item) for item in value]
    return value


def make_server(core_factory: Callable[[], Bonneaffaire] = default_core) -> MCPServer:
    server = MCPServer("bonneaffaire", instructions=INSTRUCTIONS)
    core = core_factory()

    @server.tool()
    async def search(
        keywords: Annotated[
            str | None,
            Field(description="What to look for, in plain words, e.g. 'disque dur 8 To'."),
        ] = None,
        native_url: Annotated[
            str | None,
            Field(
                description=(
                    "A Native URL: a search page address copied from a Provider's own website. "
                    "It is the whole Search request and goes only to the Provider it belongs to "
                    "(see native_urls in list_providers). Give keywords or native_url, not both; "
                    "Filters are not combined with a Native URL."
                )
            ),
        ] = None,
        providers: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Names of the Providers to ask, as list_providers shows them. "
                    "Omit to ask every enabled Provider."
                )
            ),
        ] = None,
        limit: Annotated[
            int, Field(gt=0, description="Maximum Listings each Provider returns.")
        ] = DEFAULT_LIMIT,
        price_min: Annotated[
            Money | None,
            Field(
                description=(
                    "Minimum Price as integer cents plus ISO 4217 currency, "
                    'e.g. {"cents": 5000, "currency": "EUR"} for 50 euros.'
                )
            ),
        ] = None,
        price_max: Annotated[
            Money | None,
            Field(
                description=(
                    "Maximum Price as integer cents plus ISO 4217 currency, "
                    'e.g. {"cents": 45000, "currency": "EUR"} for 450 euros.'
                )
            ),
        ] = None,
        conditions: Annotated[
            list[Condition] | None,
            Field(
                description=(
                    "Accepted Conditions; a Listing in any of them is kept. Refurbished means "
                    "professionally restored, usually with a warranty. Omit to accept all."
                )
            ),
        ] = None,
        location: Annotated[
            Location | None,
            Field(
                description=(
                    "Search around a place (city or postcode), optionally within radius_km. "
                    "Only Providers with native location support can apply it."
                )
            ),
        ] = None,
        sort: Annotated[
            Sort | None,
            Field(
                description=(
                    "Order of the merged Listings: 'price' (cheapest first) or 'recency' "
                    "(newest first). Omit to keep Provider order."
                )
            ),
        ] = None,
        extras: Annotated[
            dict[str, dict[str, str]] | None,
            Field(
                description=(
                    "Provider-specific extras: Provider name to {extra name: value}, using "
                    "the extras list_providers shows for that Provider, "
                    'e.g. {"leboncoin": {"category": "informatique"}}.'
                )
            ),
        ] = None,
    ) -> CallToolResult:
        """Search for Listings across Providers, by keywords plus Filters or by a Native URL.

        Returns merged Listings, a Provider outcome per Provider asked and a Filter report per
        Provider. Null fields are omitted.
        """
        try:
            request = SearchRequest(
                query=SearchQuery(
                    keywords=keywords,
                    native_url=native_url,
                    price_min=price_min,
                    price_max=price_max,
                    conditions=frozenset(conditions or ()),
                    location=location,
                    sort=sort,
                    extras=extras or {},
                ),
                limit=limit,
                providers=frozenset(providers) if providers else None,
            )
            result = await core.search(request)
        except (ValidationError, UnknownProvider, UnrecognisedNativeUrl) as exc:
            raise ToolError(str(exc)) from exc
        return compact(result)

    @server.tool()
    async def get_listing(
        provider: Annotated[
            str | None, Field(description="The Provider name, with provider_id.")
        ] = None,
        provider_id: Annotated[
            str | None, Field(description="The Listing's Provider ID, as Search returned it.")
        ] = None,
        url: Annotated[
            str | None,
            Field(description="A Listing URL, instead of provider and provider_id."),
        ] = None,
    ) -> CallToolResult:
        """Get one Listing's full details (description, photos, seller, availability).

        status says what happened: ok, not_found (the Listing is gone), unsupported (the
        Provider has no Listing details), blocked, timed_out or failed.
        """
        try:
            request = ListingRequest(provider=provider, provider_id=provider_id, url=url)
        except ValidationError as exc:
            raise ToolError(str(exc)) from exc
        return compact(await core.get_listing(request))

    @server.tool()
    def list_providers() -> CallToolResult:
        """List every Provider and what it supports: the Filters it applies natively (others are
        applied locally), whether it takes Native URLs, whether Get Listing works for it, its
        Provider-specific extras, and whether it is enabled."""
        # Not pruned: every Provider shows every capability, even when it is empty.
        return json_result(
            {"providers": [info.model_dump(mode="json") for info in core.list_providers()]}
        )

    return server


def streamable_http_app(
    core_factory: Callable[[], Bonneaffaire] = default_core, *, host: str = DEFAULT_HOST
) -> Starlette:
    """The ASGI app serving the MCP endpoint at /mcp.

    host: the address it listens on. On localhost the SDK turns on DNS rebinding protection;
    on other addresses (e.g. 0.0.0.0 in Docker behind the Cloudflare Tunnel) it does not.
    """
    return make_server(core_factory).streamable_http_app(host=host)


def serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    core_factory: Callable[[], Bonneaffaire] = default_core,
) -> None:
    """Run the MCP server over Streamable HTTP at http://host:port/mcp until interrupted."""
    uvicorn.run(streamable_http_app(core_factory, host=host), host=host, port=port)
