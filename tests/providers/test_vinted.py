"""Vinted, fed recorded responses through vinted_scraper's HTTP client (Seam 2)."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import Condition, FilterName, Money, SearchQuery, SellerKind, Sort
from bonneaffaire.providers import (
    ListingNotFound,
    ProviderBlocked,
    ProviderTimeout,
    UnexpectedShape,
)
from bonneaffaire.providers.vinted import vinted
from bonneaffaire.registry import default_core

FIXTURES = Path(__file__).parent.parent / "fixtures" / "vinted"
SEARCH = (FIXTURES / "search-disque-dur.json").read_text()
SEARCH_NEW = (FIXTURES / "search-disque-dur-neuf.json").read_text()
ITEM_PAGE = (FIXTURES / "item-10718798068.html").read_text()

LANDING = '<html lang="fr-FR"><head><title>Vinted</title></head><body></body></html>'
SEARCH_ENDPOINT = "https://api.vinted.fr/svc-catalogue/items"


def landing() -> httpx.Response:
    """The anonymous-session landing page: a session cookie and an anonymous id."""
    return httpx.Response(
        200,
        text=LANDING,
        headers={
            "content-type": "text/html; charset=utf-8",
            "set-cookie": "access_token_web=anonymous-token; Path=/; Domain=.vinted.fr",
            "x-anon-id": "anon-123",
        },
    )


class Replay:
    """Answers the landing page, then recorded responses by URL path; records requests."""

    def __init__(self, routes: dict[str, Callable[[], httpx.Response]]) -> None:
        self.routes = {"https://www.vinted.fr/": landing, **routes}
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(str(request.url.copy_with(query=None)))
        if route is None:
            return httpx.Response(404, text="not recorded")
        return route()

    def api_params(self) -> list[dict[str, str]]:
        return [
            dict(request.url.params)
            for request in self.requests
            if str(request.url).startswith(SEARCH_ENDPOINT)
        ]


def json_response(body: str, status: int = 200) -> Callable[[], httpx.Response]:
    return lambda: httpx.Response(status, text=body, headers={"content-type": "application/json"})


async def test_keyword_search_returns_listings_with_buyer_fee_and_condition():
    replay = Replay({SEARCH_ENDPOINT: json_response(SEARCH)})
    provider = vinted(transport=replay.transport())

    listings = await provider.search(SearchQuery(keywords="disque dur"), limit=50)

    assert len(listings) == 20
    first = listings[0]
    assert first.provider == "vinted"
    assert first.provider_id == "10718798068"
    assert first.title == "Funko pop Moana Tamatoa"
    assert first.url == "https://www.vinted.fr/items/10718798068-funko-pop-moana-tamatoa"
    assert first.thumbnail is not None
    assert first.thumbnail.startswith(
        "https://images1.vinted.net/t/06_01431_2yCoHpaqPWBafjzT7L4nX8i8/"
    )
    assert first.price == Money(cents=1000, currency="EUR")
    assert first.buyer_fee == Money(cents=120, currency="EUR")
    assert first.shipping is None
    assert first.total_cost is None
    assert first.condition == Condition.LIKE_NEW
    assert first.condition_label == "Très bon état"
    assert first.seller_kind == SellerKind.PRIVATE
    assert replay.api_params()[0]["search_text"] == "disque dur"


async def test_filtered_search_sends_native_filters_and_maps_new_and_pro_sellers():
    replay = Replay({SEARCH_ENDPOINT: json_response(SEARCH_NEW)})
    provider = vinted(transport=replay.transport())
    query = SearchQuery(
        keywords="disque dur",
        price_max=Money(cents=20000, currency="EUR"),
        price_min=Money(cents=450, currency="EUR"),
        conditions=frozenset({Condition.NEW}),
        sort=Sort.RECENCY,
    )

    listings = await provider.search(query, limit=96)

    params = replay.api_params()[0]
    assert params["price_to"] == "200.00"
    assert params["price_from"] == "4.50"
    assert params["attribute_ids[status]"] == "6,1"
    assert params["order"] == "newest_first"
    assert params["per_page"] == "96"
    with_tags = listings[1]
    assert with_tags.condition_label == "Neuf avec étiquette"
    assert with_tags.condition == Condition.NEW
    assert with_tags.seller_kind == SellerKind.PRIVATE
    pro = next(item for item in listings if item.provider_id == "10699215320")
    assert pro.seller_kind == SellerKind.PROFESSIONAL
    assert pro.condition_label == "Neuf sans étiquette"
    assert pro.condition == Condition.NEW
    assert pro.price == Money(cents=9499, currency="EUR")
    assert pro.buyer_fee == Money(cents=545, currency="EUR")


async def test_price_sort_asks_vinted_for_cheapest_first():
    replay = Replay({SEARCH_ENDPOINT: json_response(SEARCH)})
    provider = vinted(transport=replay.transport())

    await provider.search(SearchQuery(keywords="disque dur", sort=Sort.PRICE), limit=10)

    assert replay.api_params()[0]["order"] == "price_low_to_high"
    assert replay.api_params()[0]["per_page"] == "10"


async def test_conditions_vinted_cannot_express_return_no_listings_without_asking():
    replay = Replay({SEARCH_ENDPOINT: json_response(SEARCH)})
    provider = vinted(transport=replay.transport())
    query = SearchQuery(keywords="disque dur", conditions=frozenset({Condition.REFURBISHED}))

    assert await provider.search(query, limit=10) == []
    assert replay.api_params() == []


def test_declares_its_native_filters():
    assert vinted().capabilities.native_filters == {
        FilterName.PRICE_MIN,
        FilterName.PRICE_MAX,
        FilterName.CONDITION,
        FilterName.SORT,
    }


def blocked() -> httpx.Response:
    return httpx.Response(403, text="<html>Please enable JS and disable any ad blocker</html>")


async def test_a_blocked_landing_page_is_reported_as_blocked():
    replay = Replay({"https://www.vinted.fr/": blocked})
    provider = vinted(transport=replay.transport())

    with pytest.raises(ProviderBlocked):
        await provider.search(SearchQuery(keywords="disque dur"), limit=10)
    assert len(replay.requests) == 1, "a blocked session fetch is not retried"


def unavailable() -> httpx.Response:
    return httpx.Response(503, text="<html>Service temporarily unavailable</html>")


@pytest.mark.parametrize("route", [blocked, unavailable])
async def test_a_blocked_search_is_reported_as_blocked(route):
    replay = Replay({SEARCH_ENDPOINT: route})
    provider = vinted(transport=replay.transport())

    with pytest.raises(ProviderBlocked):
        await provider.search(SearchQuery(keywords="disque dur"), limit=10)


@pytest.mark.parametrize(
    "body",
    [
        '{"pagination": {}}',
        '{"items": [{"id": 1, "title": "no price"}]}',
        "<html>not json</html>",
    ],
)
async def test_an_unexpected_search_response_is_an_unexpected_shape(body: str):
    replay = Replay({SEARCH_ENDPOINT: json_response(body)})
    provider = vinted(transport=replay.transport())

    with pytest.raises(UnexpectedShape):
        await provider.search(SearchQuery(keywords="disque dur"), limit=10)


async def test_a_slow_vinted_is_reported_as_a_timeout():
    def too_slow() -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    provider = vinted(transport=Replay({SEARCH_ENDPOINT: too_slow}).transport())

    with pytest.raises(ProviderTimeout):
        await provider.search(SearchQuery(keywords="disque dur"), limit=10)


async def test_the_session_is_fetched_once_for_several_searches():
    replay = Replay({SEARCH_ENDPOINT: json_response(SEARCH)})
    provider = vinted(transport=replay.transport())

    await provider.search(SearchQuery(keywords="disque dur"), limit=10)
    await provider.search(SearchQuery(keywords="ssd"), limit=10)

    landings = [r for r in replay.requests if str(r.url) == "https://www.vinted.fr/"]
    assert len(landings) == 1


NATIVE_URL = (
    "https://www.vinted.fr/catalog?search_text=disque%20dur&status_ids[]=6&status_ids[]=1"
    "&brand_ids[]=15436642&brand_ids[]=319&price_to=200&currency=EUR&order=newest_first"
)


@pytest.mark.parametrize(
    ("url", "recognised"),
    [
        (NATIVE_URL, True),
        ("https://vinted.fr/catalog?search_text=ssd", True),
        ("https://www.vinted.fr/catalog/3312-figurines?search_text=funko", True),
        ("https://www.vinted.fr/items/10718798068-funko-pop-moana-tamatoa", False),
        ("https://www.vinted.de/catalog?search_text=ssd", False),
        ("https://www.leboncoin.fr/recherche?text=ssd", False),
    ],
)
def test_recognises_vinted_france_catalog_urls(url: str, recognised: bool):
    assert vinted().recognises_native_url(url) is recognised
    assert vinted().capabilities.native_urls


async def test_a_native_url_runs_the_search_it_describes():
    replay = Replay({SEARCH_ENDPOINT: json_response(SEARCH_NEW)})
    provider = vinted(transport=replay.transport())

    listings = await provider.search(SearchQuery(native_url=NATIVE_URL), limit=20)

    assert len(listings) == 8
    params = replay.api_params()[0]
    assert params["search_text"] == "disque dur"
    assert params["attribute_ids[status]"] == "6,1"
    assert params["attribute_ids[brand]"] == "15436642,319"
    assert params["price_to"] == "200"
    assert params["currency"] == "EUR"
    assert params["order"] == "newest_first"
    assert params["per_page"] == "20"


async def test_a_native_url_category_path_becomes_the_catalog_filter():
    replay = Replay({SEARCH_ENDPOINT: json_response(SEARCH)})
    provider = vinted(transport=replay.transport())
    url = "https://www.vinted.fr/catalog/3312-figurines?search_text=funko&catalog[]=99"

    await provider.search(SearchQuery(native_url=url), limit=20)

    params = replay.api_params()[0]
    assert params["attribute_ids[catalog]"] == "3312"
    assert params["search_text"] == "funko"


ITEM_ENDPOINT = "https://www.vinted.fr/items/10718798068"


def item_page(body: str = ITEM_PAGE, status: int = 200) -> Callable[[], httpx.Response]:
    return lambda: httpx.Response(
        status, text=body, headers={"content-type": "text/html; charset=utf-8"}
    )


@pytest.mark.parametrize(
    ("url", "provider_id"),
    [
        ("https://www.vinted.fr/items/10718798068-funko-pop-moana-tamatoa", "10718798068"),
        ("https://vinted.fr/items/10718798068?referrer=catalog", "10718798068"),
        ("https://www.vinted.fr/catalog?search_text=ssd", None),
        ("https://www.ldlc.com/fiche/PB00281525.html", None),
    ],
)
def test_finds_the_provider_id_in_a_vinted_listing_url(url: str, provider_id: str | None):
    assert vinted().listing_id_from_url(url) == provider_id
    assert vinted().capabilities.listing_details


async def test_listing_details_add_shipping_so_total_cost_is_known():
    replay = Replay({ITEM_ENDPOINT: item_page()})
    provider = vinted(transport=replay.transport())

    details = await provider.get_listing("10718798068")

    assert details.provider == "vinted"
    assert details.provider_id == "10718798068"
    assert details.title == "Funko pop Moana Tamatoa"
    assert details.url == "https://www.vinted.fr/items/10718798068-funko-pop-moana-tamatoa"
    assert details.price == Money(cents=1000, currency="EUR")
    assert details.buyer_fee == Money(cents=120, currency="EUR")
    assert details.shipping == Money(cents=305, currency="EUR")
    assert details.total_cost == Money(cents=1425, currency="EUR")
    assert details.condition == Condition.LIKE_NEW
    assert details.condition_label == "Très bon état"
    assert details.seller_kind == SellerKind.PRIVATE
    assert details.seller is not None
    assert details.seller.name == "seller017"
    assert details.seller.url == "https://www.vinted.fr/member/900000018"
    assert details.description is not None
    assert details.description.startswith("✅️ Excellent état et protégé")
    assert len(details.photos) == 4
    assert details.thumbnail == details.photos[0]
    assert details.availability == "InStock"
    assert details.attributes["brand"] == "Funko Pop"
    assert details.attributes["category"] == "Enfants Figurines"


async def test_a_listing_that_is_gone_is_not_found():
    provider = vinted(transport=Replay({ITEM_ENDPOINT: item_page("gone", 404)}).transport())

    with pytest.raises(ListingNotFound):
        await provider.get_listing("10718798068")


async def test_a_blocked_listing_page_is_reported_as_blocked():
    provider = vinted(transport=Replay({ITEM_ENDPOINT: blocked}).transport())

    with pytest.raises(ProviderBlocked):
        await provider.get_listing("10718798068")


async def test_a_listing_page_without_product_data_is_an_unexpected_shape():
    page = "<html><head></head><body>redesigned</body></html>"
    provider = vinted(transport=Replay({ITEM_ENDPOINT: item_page(page)}).transport())

    with pytest.raises(UnexpectedShape):
        await provider.get_listing("10718798068")


# Through the CLI, end to end over the same recorded responses.


def run(replay: Replay, *args: str) -> dict:
    app = make_app(lambda: Bonneaffaire([vinted(transport=replay.transport())]))
    result = CliRunner().invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.mark.parametrize(
    ("route", "status"),
    [(blocked, "blocked"), (json_response('{"unexpected": true}'), "failed")],
)
def test_blocked_and_unexpected_responses_become_provider_outcomes(route, status: str):
    payload = run(Replay({SEARCH_ENDPOINT: route}), "search", "disque dur")

    assert payload["listings"] == []
    assert payload["outcomes"][0]["provider"] == "vinted"
    assert payload["outcomes"][0]["status"] == status


def test_keyword_search_returns_vinted_listings():
    payload = run(Replay({SEARCH_ENDPOINT: json_response(SEARCH)}), "search", "disque dur")

    assert payload["outcomes"][0]["status"] == "ok"
    assert len(payload["listings"]) == 20
    assert {item["provider"] for item in payload["listings"]} == {"vinted"}
    assert payload["listings"][0]["buyer_fee"] == {"cents": 120, "currency": "EUR"}


def test_filtered_search_is_applied_by_vinted_itself():
    replay = Replay({SEARCH_ENDPOINT: json_response(SEARCH_NEW)})

    payload = run(replay, "search", "disque dur", "--condition", "New", "--max-price", "200")

    assert replay.api_params()[0]["attribute_ids[status]"] == "6,1"
    assert payload["filter_reports"][0]["native"] == ["price_max", "condition"]
    assert payload["filter_reports"][0]["local"] == []
    assert len(payload["listings"]) == 8
    assert {item["condition"] for item in payload["listings"]} == {"New"}


def test_a_pasted_vinted_url_returns_vinted_listings():
    replay = Replay({SEARCH_ENDPOINT: json_response(SEARCH_NEW)})

    payload = run(replay, "search", "https://www.vinted.fr/catalog?search_text=ssd&status_ids[]=6")

    assert replay.api_params()[0]["search_text"] == "ssd"
    assert {item["provider"] for item in payload["listings"]} == {"vinted"}


def test_listing_details_for_a_vinted_url():
    replay = Replay({ITEM_ENDPOINT: item_page()})

    payload = run(
        replay, "listing", "https://www.vinted.fr/items/10718798068-funko-pop-moana-tamatoa"
    )

    assert payload["status"] == "ok"
    assert payload["listing"]["total_cost"] == {"cents": 1425, "currency": "EUR"}


def test_vinted_is_registered_and_enabled_by_default():
    assert "vinted" in [provider.name for provider in default_core({}).providers]
    disabled = default_core({"BONNEAFFAIRE_DISABLED_PROVIDERS": "vinted"})
    assert "vinted" not in [provider.name for provider in disabled.providers]
