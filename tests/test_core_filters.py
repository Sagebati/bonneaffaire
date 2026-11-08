"""Filters at the core Search seam, with fake Providers declaring different native Filters."""

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import (
    Condition,
    FilterName,
    Listing,
    Location,
    Money,
    SearchQuery,
    SearchRequest,
    SellerKind,
    Sort,
)
from bonneaffaire.providers import Capabilities


def euros(amount: int) -> Money:
    return Money(cents=amount * 100, currency="EUR")


def listing(provider: str, provider_id: str, price: int, **overrides: object) -> Listing:
    fields: dict[str, object] = {
        "provider": provider,
        "provider_id": provider_id,
        "title": f"Disque {provider_id}",
        "url": f"https://{provider}.example/{provider_id}",
        "price": euros(price),
        "condition": Condition.USED,
        "seller_kind": SellerKind.PRIVATE,
    }
    fields.update(overrides)
    return Listing.model_validate(fields)


class DumbProvider:
    """Applies no Filter itself: returns everything it has."""

    country = "FR"
    capabilities = Capabilities()

    def __init__(self, name: str, listings: list[Listing]) -> None:
        self.name = name
        self.listings = listings
        self.queries: list[SearchQuery] = []

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        self.queries.append(query)
        return self.listings[:limit]


async def test_a_provider_without_native_filters_has_price_filtered_locally():
    provider = DumbProvider(
        "dumb",
        [listing("dumb", "cheap", 50), listing("dumb", "ok", 120), listing("dumb", "dear", 300)],
    )
    core = Bonneaffaire([provider])

    result = await core.search(
        SearchRequest(
            query=SearchQuery(keywords="disque", price_min=euros(100), price_max=euros(200))
        )
    )

    assert [item.provider_id for item in result.listings] == ["ok"]
    report = result.filter_reports[0]
    assert report.provider == "dumb"
    assert report.native == []
    assert report.local == [FilterName.PRICE_MIN, FilterName.PRICE_MAX]
    assert report.unapplied == []


class SmartProvider:
    """Applies price and Condition Filters itself, as a Provider with a rich search URL would."""

    country = "FR"
    capabilities = Capabilities(
        native_filters=frozenset({FilterName.PRICE_MIN, FilterName.PRICE_MAX, FilterName.CONDITION})
    )

    def __init__(self, name: str, listings: list[Listing]) -> None:
        self.name = name
        self.listings = listings
        self.queries: list[SearchQuery] = []

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        self.queries.append(query)
        kept = [
            item
            for item in self.listings
            if (query.price_min is None or item.price.cents >= query.price_min.cents)
            and (query.price_max is None or item.price.cents <= query.price_max.cents)
            and (not query.conditions or item.condition in query.conditions)
        ]
        return kept[:limit]


async def test_condition_and_price_exclude_listings_whether_applied_natively_or_locally():
    def stock(name: str) -> list[Listing]:
        return [
            listing(name, "new", 150, condition=Condition.NEW),
            listing(name, "used", 150, condition=Condition.USED),
            listing(name, "broken", 150, condition=Condition.FOR_PARTS),
            listing(name, "unknown", 150, condition=Condition.UNKNOWN),
            listing(name, "new-dear", 900, condition=Condition.NEW),
        ]

    core = Bonneaffaire(
        [SmartProvider("smart", stock("smart")), DumbProvider("dumb", stock("dumb"))]
    )

    result = await core.search(
        SearchRequest(
            query=SearchQuery(
                keywords="disque",
                price_max=euros(200),
                conditions=frozenset({Condition.NEW, Condition.USED}),
            )
        )
    )

    assert sorted((item.provider, item.provider_id) for item in result.listings) == [
        ("dumb", "new"),
        ("dumb", "used"),
        ("smart", "new"),
        ("smart", "used"),
    ]
    reports = {report.provider: report for report in result.filter_reports}
    assert reports["smart"].native == [FilterName.PRICE_MAX, FilterName.CONDITION]
    assert reports["smart"].local == []
    assert reports["dumb"].native == []
    assert reports["dumb"].local == [FilterName.PRICE_MAX, FilterName.CONDITION]


class LocalMarketProvider(DumbProvider):
    """Searches around a place itself, like a classifieds site."""

    capabilities = Capabilities(native_filters=frozenset({FilterName.LOCATION}))


async def test_a_location_filter_no_one_can_apply_is_reported_not_silently_dropped():
    near = DumbProvider("near", [listing("near", "a", 100, location="Lyon")])
    retail = DumbProvider("retail", [listing("retail", "b", 100)])
    market = LocalMarketProvider("market", [listing("market", "c", 100, location="Lyon")])
    core = Bonneaffaire([near, retail, market])

    result = await core.search(
        SearchRequest(
            query=SearchQuery(keywords="disque", location=Location(place="Lyon", radius_km=20))
        )
    )

    reports = {report.provider: report for report in result.filter_reports}
    assert reports["market"].native == [FilterName.LOCATION]
    assert reports["market"].unapplied == []
    assert reports["retail"].unapplied == [FilterName.LOCATION]
    assert reports["near"].unapplied == [FilterName.LOCATION]
    assert market.queries[0].location == Location(place="Lyon", radius_km=20)
    assert {item.provider_id for item in result.listings} == {"a", "b", "c"}


class CheapestFirstProvider(DumbProvider):
    capabilities = Capabilities(native_filters=frozenset({FilterName.SORT}))


async def test_sort_is_reported_native_for_providers_that_sort_and_local_for_the_rest():
    one = CheapestFirstProvider("one", [listing("one", "one-200", 200)])
    two = DumbProvider("two", [listing("two", "two-100", 100)])
    core = Bonneaffaire([one, two])

    result = await core.search(SearchRequest(query=SearchQuery(keywords="disque", sort=Sort.PRICE)))

    assert [item.provider_id for item in result.listings] == ["two-100", "one-200"]
    reports = {report.provider: report for report in result.filter_reports}
    assert reports["one"].native == [FilterName.SORT]
    assert reports["two"].local == [FilterName.SORT]


class CategoryProvider(DumbProvider):
    capabilities = Capabilities(extras=frozenset({"category"}))


async def test_extras_reach_only_the_provider_that_declares_them():
    classifieds = CategoryProvider("classifieds", [])
    other = DumbProvider("other", [])
    core = Bonneaffaire([classifieds, other])

    result = await core.search(
        SearchRequest(
            query=SearchQuery(
                keywords="disque",
                extras={
                    "classifieds": {"category": "15", "colour": "red"},
                    "other": {"category": "3"},
                },
            )
        )
    )

    assert classifieds.queries[0].extras == {"classifieds": {"category": "15"}}
    assert other.queries[0].extras == {}
    reports = {report.provider: report for report in result.filter_reports}
    assert reports["classifieds"].ignored_extras == ["colour"]
    assert reports["other"].ignored_extras == ["category"]
