"""eBay, fed Browse API responses (Seam 2). See tests/fixtures/ebay/README.md for their origin."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import (
    Condition,
    FilterName,
    Money,
    SearchQuery,
    Seller,
    SellerKind,
    Sort,
)
from bonneaffaire.providers import (
    ListingNotFound,
    ProviderBlocked,
    ProviderError,
    ProviderTimeout,
    UnexpectedShape,
)
from bonneaffaire.providers.ebay import EbayCredentials, EbayProvider, ebay

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ebay"
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_PATH = "/buy/browse/v1/item_summary/search"
CREDENTIALS = EbayCredentials(client_id="my-app-id", client_secret="my-cert-id")


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


class FakeEbay:
    """Answers the token endpoint and Browse API paths; records every request."""

    def __init__(
        self,
        routes: dict[str, Callable[[httpx.Request], httpx.Response]],
        token_error: httpx.Response | None = None,
    ) -> None:
        self.routes = routes
        self.token_error = token_error
        self.requests: list[httpx.Request] = []
        self.tokens_issued = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == TOKEN_URL:
            if self.token_error is not None:
                return self.token_error
            self.tokens_issued += 1
            body = fixture("token-response.json")
            body["access_token"] = f"token-{self.tokens_issued}"
            return httpx.Response(200, json=body)
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"errors": [{"errorId": 11001}]})
        return route(request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def api_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if str(r.url) != TOKEN_URL]


def answer(body: Any, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, json=body)


async def test_keyword_search_returns_listings_from_the_browse_api():
    fake = FakeEbay({SEARCH_PATH: answer(fixture("search-fr-disque-dur-8-to.json"))})
    provider = ebay(CREDENTIALS, client=fake.client())

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)

    assert [listing.provider_id for listing in listings] == [
        "v1|306123456789|0",
        "v1|126234567890|0",
        "v1|176345678901|0",
        "v1|256456789012|0",
        "v1|335567890123|0",
    ]
    first = listings[0]
    assert first.provider == "ebay"
    assert first.title == "Seagate IronWolf 8 To NAS ST8000VN004"
    assert first.url == "https://www.ebay.fr/itm/306123456789"
    assert first.thumbnail == "https://i.ebayimg.com/thumbs/images/g/AAAAAAAAAAAAAAAA/s-l225.jpg"
    assert first.price == Money(cents=18990, currency="EUR")
    assert first.shipping == Money(cents=0, currency="EUR")
    assert first.condition == Condition.NEW
    assert first.condition_label == "Neuf"
    assert first.seller_kind == SellerKind.PROFESSIONAL
    assert first.location == "75***, FR"
    assert first.posted_at == datetime(2026, 10, 30, 9, 12, tzinfo=UTC)
    request = fake.api_requests()[0]
    assert request.url.params["q"] == "disque dur 8 To"
    assert request.headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_FR"
    assert request.headers["Authorization"] == "Bearer token-1"


def test_declares_price_condition_and_sort_as_native_filters_and_listing_details():
    capabilities = ebay(CREDENTIALS).capabilities

    assert capabilities.native_filters == {
        FilterName.PRICE_MIN,
        FilterName.PRICE_MAX,
        FilterName.CONDITION,
        FilterName.SORT,
    }
    assert capabilities.listing_details


async def test_filtered_search_sends_price_condition_and_sort_to_ebay():
    fake = FakeEbay({SEARCH_PATH: answer({"total": 0, "limit": 20, "offset": 0})})
    provider = ebay(CREDENTIALS, client=fake.client())
    query = SearchQuery(
        keywords="disque dur",
        price_min=Money(cents=5000, currency="EUR"),
        price_max=Money(cents=15050, currency="EUR"),
        conditions=frozenset({Condition.NEW, Condition.FOR_PARTS}),
        sort=Sort.PRICE,
    )

    listings = await provider.search(query, limit=20)

    assert listings == []
    params = fake.api_requests()[0].url.params
    assert params["limit"] == "20"
    assert params["filter"] == "price:[50.00..150.50],priceCurrency:EUR,conditionIds:{1000|7000}"
    assert params["sort"] == "price"


async def test_open_ended_price_range_and_recency_sort():
    fake = FakeEbay({SEARCH_PATH: answer({"total": 0})})
    provider = ebay(CREDENTIALS, client=fake.client())

    await provider.search(
        SearchQuery(keywords="nas", price_min=Money(cents=1000, currency="EUR"), sort=Sort.RECENCY),
        limit=500,
    )
    await provider.search(
        SearchQuery(keywords="nas", price_max=Money(cents=9999, currency="EUR")), limit=10
    )

    first, second = (request.url.params for request in fake.api_requests())
    assert first["filter"] == "price:[10.00],priceCurrency:EUR"
    assert first["sort"] == "newlyListed"
    assert first["limit"] == "200", "the Browse API returns at most 200 items per page"
    assert second["filter"] == "price:[..99.99],priceCurrency:EUR"
    assert "sort" not in second


async def test_listings_outside_the_condition_filter_are_dropped():
    """eBay cannot filter on Unknown Condition, so the Provider checks what comes back."""
    fake = FakeEbay({SEARCH_PATH: answer(fixture("search-fr-disque-dur-8-to.json"))})
    provider = ebay(CREDENTIALS, client=fake.client())
    query = SearchQuery(keywords="disque dur", conditions=frozenset({Condition.USED}))

    listings = await provider.search(query, limit=50)

    assert [listing.provider_id for listing in listings] == ["v1|176345678901|0"]


ITEM_PATH = "/buy/browse/v1/item/v1|176345678901|0"


async def test_listing_details_come_from_the_details_endpoint():
    fake = FakeEbay({ITEM_PATH: answer(fixture("item-fr-176345678901.json"))})
    provider = ebay(CREDENTIALS, client=fake.client())

    details = await provider.get_listing("v1|176345678901|0")

    assert details.provider == "ebay"
    assert details.provider_id == "v1|176345678901|0"
    assert details.title == "Disque dur Seagate Barracuda 8 To"
    assert details.url == "https://www.ebay.fr/itm/176345678901"
    assert details.price == Money(cents=8500, currency="EUR")
    assert details.shipping == Money(cents=750, currency="EUR")
    assert details.condition == Condition.USED
    assert details.condition_label == "Occasion"
    assert details.seller_kind == SellerKind.PRIVATE
    assert details.seller == Seller(name="jdupont69", url="https://www.ebay.fr/usr/jdupont69")
    assert details.location == "Lyon, 69***, FR"
    assert details.availability == "IN_STOCK"
    assert (
        details.description
        == "Disque dur Seagate Barracuda 8 To.\nTesté avec CrystalDiskInfo : état bon."
    )
    assert details.photos == [
        "https://i.ebayimg.com/images/g/CCCCCCCCCCCCCCCC/s-l1600.jpg",
        "https://i.ebayimg.com/images/g/CCCCCCCCCCCCCCC2/s-l1600.jpg",
        "https://i.ebayimg.com/images/g/CCCCCCCCCCCCCCC3/s-l1600.jpg",
    ]
    assert details.attributes["condition_description"] == (
        "Fonctionne parfaitement, aucun secteur défectueux."
    )
    assert details.attributes["brand"] == "Seagate"
    assert details.attributes["mpn"] == "ST8000DM004"
    assert fake.api_requests()[0].headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_FR"


async def test_the_documented_details_sample_parses():
    sample = fixture("item-doc-sample.json")
    fake = FakeEbay({"/buy/browse/v1/item/v1|1**********0|0": answer(sample)})
    provider = ebay(CREDENTIALS, client=fake.client())

    details = await provider.get_listing("v1|1**********0|0")

    assert details.title == "Sample Item"
    assert details.price == Money(cents=2900, currency="USD")
    assert details.shipping == Money(cents=95000, currency="USD")
    assert details.condition == Condition.NEW
    assert details.seller_kind == SellerKind.UNKNOWN
    assert details.availability == "IN_STOCK"
    assert details.photos == ["https://i.ebayimg.com/images/g/Z**********l/s-l1600.jpg"]


async def test_an_ended_or_unknown_listing_is_not_found():
    error = {"errors": [{"errorId": 11001, "message": "The specified item ID was not found."}]}
    fake = FakeEbay({ITEM_PATH: answer(error, status=404)})
    provider = ebay(CREDENTIALS, client=fake.client())

    with pytest.raises(ListingNotFound) as raised:
        await provider.get_listing("v1|176345678901|0")

    assert "was not found" in raised.value.message


def test_listing_urls_give_the_provider_id():
    provider = ebay(CREDENTIALS)

    assert provider.listing_id_from_url("https://www.ebay.fr/itm/176345678901") == (
        "v1|176345678901|0"
    )
    assert provider.listing_id_from_url(
        "https://www.ebay.fr/itm/Disque-dur-8-To/176345678901?hash=item2&var=0"
    ) == ("v1|176345678901|0")
    assert provider.listing_id_from_url("https://ebay.com/itm/176345678901") == (
        "v1|176345678901|0"
    )
    assert provider.listing_id_from_url("https://www.ldlc.com/fiche/PB00281525.html") is None
    assert provider.listing_id_from_url("https://www.ebay.fr/sch/i.html?_nkw=nas") is None


EMPTY_SEARCH = {SEARCH_PATH: answer({"total": 0})}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_the_token_is_obtained_with_client_credentials_and_reused():
    fake = FakeEbay(EMPTY_SEARCH)
    provider = ebay(CREDENTIALS, client=fake.client())

    await provider.search(SearchQuery(keywords="nas"), limit=10)
    await provider.search(SearchQuery(keywords="nas"), limit=10)

    assert fake.tokens_issued == 1
    token_request = fake.requests[0]
    assert token_request.method == "POST"
    assert token_request.headers["Authorization"] == "Basic bXktYXBwLWlkOm15LWNlcnQtaWQ="
    assert dict(httpx.QueryParams(token_request.content.decode())) == {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }
    assert [r.headers["Authorization"] for r in fake.api_requests()] == ["Bearer token-1"] * 2


async def test_the_token_is_refreshed_shortly_before_it_expires():
    fake = FakeEbay(EMPTY_SEARCH)
    clock = Clock()
    provider = EbayProvider(CREDENTIALS, client=fake.client(), clock=clock)

    await provider.search(SearchQuery(keywords="nas"), limit=10)
    clock.now += 7200 - 30
    await provider.search(SearchQuery(keywords="nas"), limit=10)

    assert [r.headers["Authorization"] for r in fake.api_requests()] == [
        "Bearer token-1",
        "Bearer token-2",
    ]


async def test_a_rejected_token_is_refreshed_and_the_call_retried_once():
    calls = []

    def search(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer token-1":
            return httpx.Response(401, json={"errors": [{"errorId": 1001}]})
        return httpx.Response(200, json={"total": 0})

    fake = FakeEbay({SEARCH_PATH: search})
    provider = ebay(CREDENTIALS, client=fake.client())

    assert await provider.search(SearchQuery(keywords="nas"), limit=10) == []
    assert calls == ["Bearer token-1", "Bearer token-2"]


async def test_rejected_credentials_fail_with_a_clear_message():
    fake = FakeEbay(
        EMPTY_SEARCH,
        token_error=httpx.Response(
            401,
            json={"error": "invalid_client", "error_description": "client authentication failed"},
        ),
    )
    provider = ebay(CREDENTIALS, client=fake.client())

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchQuery(keywords="nas"), limit=10)

    assert not isinstance(raised.value, ProviderBlocked)
    assert "credentials" in raised.value.message
    assert "client authentication failed" in raised.value.message


async def test_rate_limiting_is_reported_as_blocked():
    error = {"errors": [{"errorId": 2001, "message": "Too many requests"}]}
    fake = FakeEbay({SEARCH_PATH: answer(error, status=429)})
    provider = ebay(CREDENTIALS, client=fake.client())

    with pytest.raises(ProviderBlocked) as raised:
        await provider.search(SearchQuery(keywords="nas"), limit=10)

    assert "rate limit" in raised.value.message


async def test_missing_buy_api_access_fails_with_a_clear_message():
    error = {"errors": [{"errorId": 1100, "message": "Insufficient permissions"}]}
    fake = FakeEbay({SEARCH_PATH: answer(error, status=403)})
    provider = ebay(CREDENTIALS, client=fake.client())

    with pytest.raises(ProviderError) as raised:
        await provider.search(SearchQuery(keywords="nas"), limit=10)

    assert "Insufficient permissions" in raised.value.message
    assert "403" in raised.value.message


async def test_a_timeout_is_reported_as_timed_out():
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = ebay(CREDENTIALS, client=FakeEbay({SEARCH_PATH: slow}).client())

    with pytest.raises(ProviderTimeout):
        await provider.search(SearchQuery(keywords="nas"), limit=10)


async def test_a_response_without_json_is_an_unexpected_shape():
    def html(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    provider = ebay(CREDENTIALS, client=FakeEbay({SEARCH_PATH: html}).client())

    with pytest.raises(UnexpectedShape):
        await provider.search(SearchQuery(keywords="nas"), limit=10)


async def test_condition_ids_map_to_conditions_and_keep_the_raw_label():
    fake = FakeEbay({SEARCH_PATH: answer(fixture("search-fr-disque-dur-8-to.json"))})
    provider = ebay(CREDENTIALS, client=fake.client())

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)

    assert [(listing.condition, listing.condition_label) for listing in listings] == [
        (Condition.NEW, "Neuf"),
        (Condition.REFURBISHED, "Excellent - Reconditionné"),
        (Condition.USED, "Occasion"),
        (Condition.FOR_PARTS, "Pour pièces détachées/ne fonctionne pas"),
        (Condition.LIKE_NEW, "Neuf autre (voir détails)"),
    ]
    assert [listing.attributes["condition_id"] for listing in listings] == [
        "1000",
        "2010",
        "3000",
        "7000",
        "1500",
    ]


async def test_shipping_is_the_cheapest_stated_cost_and_unknown_when_calculated_or_missing():
    fake = FakeEbay({SEARCH_PATH: answer(fixture("search-fr-disque-dur-8-to.json"))})
    provider = ebay(CREDENTIALS, client=fake.client())

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)

    assert [listing.shipping for listing in listings] == [
        Money(cents=0, currency="EUR"),
        Money(cents=690, currency="EUR"),
        None,
        None,
        Money(cents=490, currency="EUR"),
    ]


async def test_seller_kind_comes_from_the_seller_account_type():
    fake = FakeEbay({SEARCH_PATH: answer(fixture("search-fr-disque-dur-8-to.json"))})
    provider = ebay(CREDENTIALS, client=fake.client())

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)

    assert [listing.seller_kind for listing in listings] == [
        SellerKind.PROFESSIONAL,
        SellerKind.PROFESSIONAL,
        SellerKind.PRIVATE,
        SellerKind.PRIVATE,
        SellerKind.UNKNOWN,
    ]


async def test_the_documented_search_sample_parses():
    sample = fixture("search-doc-sample-iphone-price-condition.json")
    fake = FakeEbay({SEARCH_PATH: answer(sample)})
    provider = ebay(CREDENTIALS, client=fake.client())

    listings = await provider.search(SearchQuery(keywords="iphone"), limit=50)

    assert len(listings) == 5
    first, second = listings[:2]
    assert first.price == Money(cents=39999, currency="USD")
    assert first.condition == Condition.LIKE_NEW
    assert first.condition_label == "New other (see details)"
    assert first.shipping == Money(cents=0, currency="USD")
    assert first.seller_kind == SellerKind.UNKNOWN
    assert second.condition == Condition.NEW
    assert second.shipping is None


def test_a_filtered_search_through_the_cli_returns_ebay_listings():
    fake = FakeEbay({SEARCH_PATH: answer(fixture("search-fr-disque-dur-8-to.json"))})
    app = make_app(lambda: Bonneaffaire([ebay(CREDENTIALS, client=fake.client())]))

    result = CliRunner().invoke(
        app,
        ["search", "disque", "dur", "--max-price", "200", "--condition", "Used", "--json"],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert [item["provider_id"] for item in output["listings"]] == ["v1|176345678901|0"]
    assert output["filter_reports"][0]["native"] == ["price_max", "condition"]
    assert output["filter_reports"][0]["local"] == []
    assert fake.api_requests()[0].url.params["filter"] == (
        "price:[..200.00],priceCurrency:EUR,conditionIds:{2990|3000|3010|4000|5000|6000}"
    )


def test_listing_details_through_the_cli_by_ebay_url():
    fake = FakeEbay({ITEM_PATH: answer(fixture("item-fr-176345678901.json"))})
    app = make_app(lambda: Bonneaffaire([ebay(CREDENTIALS, client=fake.client())]))

    result = CliRunner().invoke(app, ["listing", "https://www.ebay.fr/itm/176345678901", "--json"])

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["status"] == "ok"
    assert output["listing"]["seller"]["name"] == "jdupont69"
