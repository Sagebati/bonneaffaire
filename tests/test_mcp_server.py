"""The MCP server: a thin adapter that calls the core and serialises its results."""

import json
import socket
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import httpx
import uvicorn
from mcp import Client
from mcp.types import CallToolResult, TextContent

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import (
    Condition,
    FilterName,
    Listing,
    ListingDetails,
    Location,
    Money,
    SearchQuery,
    SellerKind,
    Sort,
)
from bonneaffaire.providers import Capabilities, ListingNotFound
from bonneaffaire.server import make_server, streamable_http_app

LISTING = Listing(
    provider="shop",
    provider_id="PB1",
    title="IronWolf 8 To",
    url="https://shop.example/PB1",
    price=Money(cents=44995, currency="EUR"),
    condition=Condition.NEW,
    seller_kind=SellerKind.PROFESSIONAL,
)


class FakeShop:
    name = "shop"
    country = "FR"
    capabilities = Capabilities(
        native_filters=frozenset({FilterName.SORT}),
        native_urls=True,
        listing_details=True,
        extras=frozenset({"category"}),
    )

    def __init__(self) -> None:
        self.asked: list[tuple[SearchQuery, int]] = []

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        self.asked.append((query, limit))
        return [LISTING]

    def recognises_native_url(self, url: str) -> bool:
        return url.startswith("https://shop.example/search")

    def listing_id_from_url(self, url: str) -> str | None:
        return url.removeprefix("https://shop.example/") if url.startswith("https://shop") else None

    async def get_listing(self, provider_id: str) -> ListingDetails:
        if provider_id != "PB1":
            raise ListingNotFound(self.name, f"{provider_id} is gone")
        return ListingDetails(**LISTING.model_dump(exclude={"total_cost"}), description="8 To")


def text(result: CallToolResult) -> str:
    content = result.content[0]
    assert isinstance(content, TextContent)
    return content.text


def payload(result: CallToolResult) -> dict[str, Any]:
    """The result as JSON, checking the text is compact and matches the structured content."""
    assert not result.is_error, result.content
    assert "\n" not in text(result) and '": ' not in text(result)
    assert json.loads(text(result)) == result.structured_content
    assert result.structured_content is not None
    return result.structured_content


async def test_search_passes_filters_to_the_core_and_returns_compact_json():
    shop = FakeShop()
    async with Client(make_server(lambda: Bonneaffaire([shop]))) as client:
        result = await client.call_tool(
            "search",
            {
                "keywords": "disque dur",
                "providers": ["shop"],
                "limit": 5,
                "price_max": {"cents": 50000, "currency": "EUR"},
                "conditions": ["New", "Refurbished"],
                "location": {"place": "Lyon", "radius_km": 20},
                "sort": "price",
                "extras": {"shop": {"category": "disks"}},
            },
        )

    assert shop.asked == [
        (
            SearchQuery(
                keywords="disque dur",
                price_max=Money(cents=50000, currency="EUR"),
                conditions=frozenset({Condition.NEW, Condition.REFURBISHED}),
                location=Location(place="Lyon", radius_km=20),
                sort=Sort.PRICE,
                extras={"shop": {"category": "disks"}},
            ),
            5,
        )
    ]
    body = payload(result)
    assert body == {
        "listings": [
            {
                "provider": "shop",
                "provider_id": "PB1",
                "title": "IronWolf 8 To",
                "url": "https://shop.example/PB1",
                "price": {"cents": 44995, "currency": "EUR"},
                "condition": "New",
                "seller_kind": "Professional",
            }
        ],
        "outcomes": [{"provider": "shop", "status": "ok", "listing_count": 1}],
        "filter_reports": [
            {
                "provider": "shop",
                "native": ["sort"],
                "local": ["price_max", "condition"],
                "unapplied": ["location"],
            }
        ],
    }


async def test_search_takes_a_native_url():
    shop = FakeShop()
    async with Client(make_server(lambda: Bonneaffaire([shop]))) as client:
        result = await client.call_tool(
            "search", {"native_url": "https://shop.example/search?q=disque"}
        )

    assert payload(result)["outcomes"][0]["status"] == "ok"
    assert shop.asked[0][0] == SearchQuery(native_url="https://shop.example/search?q=disque")


async def test_bad_search_requests_are_tool_errors():
    async with Client(make_server(lambda: Bonneaffaire([FakeShop()]))) as client:
        unknown = await client.call_tool("search", {"keywords": "x", "providers": ["nope"]})
        unrecognised = await client.call_tool("search", {"native_url": "https://else.example/"})
        neither = await client.call_tool("search", {})

    assert unknown.is_error and "nope" in text(unknown)
    assert unrecognised.is_error and "Native URL" in text(unrecognised)
    assert neither.is_error


async def test_a_native_url_with_filters_is_a_tool_error():
    shop = FakeShop()
    async with Client(make_server(lambda: Bonneaffaire([shop]))) as client:
        result = await client.call_tool(
            "search", {"native_url": "https://shop.example/search?q=disque", "sort": "price"}
        )

    assert result.is_error and "Native URL is the whole Search" in text(result)
    assert shop.asked == []


async def test_get_listing_by_provider_id_or_url():
    async with Client(make_server(lambda: Bonneaffaire([FakeShop()]))) as client:
        by_id = await client.call_tool("get_listing", {"provider": "shop", "provider_id": "PB1"})
        by_url = await client.call_tool("get_listing", {"url": "https://shop.example/PB1"})
        gone = await client.call_tool("get_listing", {"provider": "shop", "provider_id": "PB9"})

    assert payload(by_id)["listing"]["description"] == "8 To"
    assert payload(by_url)["status"] == "ok"
    assert payload(gone) == {"status": "not_found", "provider": "shop", "message": "PB9 is gone"}


async def test_list_providers_derives_from_provider_capabilities():
    async with Client(make_server(lambda: Bonneaffaire([FakeShop()]))) as client:
        result = await client.call_tool("list_providers", {})

    assert payload(result) == {
        "providers": [
            {
                "name": "shop",
                "country": "FR",
                "enabled": True,
                "native_filters": ["sort"],
                "native_urls": True,
                "listing_details": True,
                "extras": ["category"],
                "disabled_reason": None,
            }
        ]
    }


async def test_search_schema_describes_filters_conditions_and_native_url():
    async with Client(make_server(lambda: Bonneaffaire([FakeShop()]))) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert set(tools) == {"search", "get_listing", "list_providers"}
    schema = json.dumps(tools["search"].input_schema)
    for value in Condition:
        assert f'"{value}"' in schema
    for words in ("Native URL", "list_providers", "cents", "radius_km", "price", "recency"):
        assert words in schema


async def test_an_mcp_client_calls_the_tools_over_streamable_http():
    shop = FakeShop()
    with running_server(lambda: Bonneaffaire([shop])) as url:
        async with Client(url) as client:
            providers = await client.call_tool("list_providers", {})
            found = await client.call_tool("search", {"keywords": "disque"})

    assert payload(providers)["providers"][0]["name"] == "shop"
    assert payload(found)["listings"][0]["provider_id"] == "PB1"


def test_health_check_reports_the_service_is_up():
    with running_server(lambda: Bonneaffaire([FakeShop()])) as url:
        response = httpx.get(url.removesuffix("/mcp") + "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "enabled_providers": ["shop"]}


@contextmanager
def running_server(core_factory: Callable[[], Bonneaffaire]) -> Generator[str]:
    """Serve over real HTTP on a free local port; yield the MCP endpoint URL."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(
        streamable_http_app(core_factory, host="127.0.0.1"),
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        while not server.started:
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
