"""The core Search, with fake Providers (Seam 1)."""

import asyncio
from datetime import UTC, datetime

import pytest

from bonneaffaire.core import Bonneaffaire, UnknownProvider
from bonneaffaire.models import (
    Condition,
    Listing,
    Money,
    OutcomeStatus,
    SearchQuery,
    SearchRequest,
    SellerKind,
    Sort,
)
from bonneaffaire.providers import (
    Capabilities,
    ProviderBlocked,
    ProviderTimeout,
    UnexpectedShape,
)


def listing(provider_id: str, **overrides: object) -> Listing:
    fields: dict[str, object] = {
        "provider": "fake",
        "provider_id": provider_id,
        "title": f"Disque {provider_id}",
        "url": f"https://fake.example/{provider_id}",
        "price": Money(cents=10000, currency="EUR"),
        "condition": Condition.USED,
        "seller_kind": SellerKind.PRIVATE,
    }
    fields.update(overrides)
    return Listing.model_validate(fields)


class FakeProvider:
    country = "FR"
    capabilities = Capabilities()

    def __init__(self, listings: list[Listing], name: str = "fake") -> None:
        self.name = name
        self.listings = listings
        self.queries: list[SearchQuery] = []

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        self.queries.append(query)
        return self.listings[:limit]


async def test_search_returns_the_providers_listings_and_an_ok_outcome():
    provider = FakeProvider([listing("a"), listing("b")])
    core = Bonneaffaire([provider])

    result = await core.search(SearchRequest(query=SearchQuery(keywords="disque dur")))

    assert [item.provider_id for item in result.listings] == ["a", "b"]
    assert [(o.provider, o.status, o.listing_count) for o in result.outcomes] == [
        ("fake", OutcomeStatus.OK, 2)
    ]
    assert provider.queries == [SearchQuery(keywords="disque dur")]


async def test_search_respects_the_per_provider_limit():
    core = Bonneaffaire([FakeProvider([listing(str(n)) for n in range(80)])])

    default = await core.search(SearchRequest(query=SearchQuery(keywords="x")))
    three = await core.search(SearchRequest(query=SearchQuery(keywords="x"), limit=3))

    assert len(default.listings) == 50
    assert len(three.listings) == 3


async def test_total_cost_is_present_only_when_price_shipping_and_buyer_fee_are_all_known():
    eur = "EUR"
    complete = listing(
        "complete",
        shipping=Money(cents=499, currency=eur),
        buyer_fee=Money(cents=270, currency=eur),
    )
    no_fee = listing("no-fee", shipping=Money(cents=499, currency=eur))
    no_shipping = listing("no-shipping", buyer_fee=Money(cents=270, currency=eur))
    core = Bonneaffaire([FakeProvider([complete, no_fee, no_shipping])])

    result = await core.search(SearchRequest(query=SearchQuery(keywords="x")))

    totals = {item.provider_id: item.total_cost for item in result.listings}
    assert totals == {
        "complete": Money(cents=10769, currency=eur),
        "no-fee": None,
        "no-shipping": None,
    }
    assert result.model_dump(mode="json")["listings"][0]["total_cost"] == {
        "cents": 10769,
        "currency": "EUR",
    }
    assert result.model_dump(mode="json")["listings"][1]["total_cost"] is None


def keywords(text: str = "x", **request: object) -> SearchRequest:
    return SearchRequest.model_validate({"query": SearchQuery(keywords=text), **request})


async def test_search_merges_listings_from_all_providers_with_an_outcome_each():
    alpha = FakeProvider([listing("a1", provider="alpha")], name="alpha")
    beta = FakeProvider([listing("b1", provider="beta"), listing("b2", provider="beta")], "beta")
    core = Bonneaffaire([alpha, beta])

    result = await core.search(keywords())

    assert sorted(item.provider_id for item in result.listings) == ["a1", "b1", "b2"]
    assert [(o.provider, o.status, o.listing_count) for o in result.outcomes] == [
        ("alpha", OutcomeStatus.OK, 1),
        ("beta", OutcomeStatus.OK, 2),
    ]


async def test_search_can_target_a_subset_of_providers():
    alpha = FakeProvider([listing("a1", provider="alpha")], name="alpha")
    beta = FakeProvider([listing("b1", provider="beta")], name="beta")
    core = Bonneaffaire([alpha, beta])

    result = await core.search(keywords(providers=["beta"]))

    assert [item.provider_id for item in result.listings] == ["b1"]
    assert [o.provider for o in result.outcomes] == ["beta"]
    assert alpha.queries == []


async def test_disabled_providers_are_not_asked_and_cannot_be_selected():
    alpha = FakeProvider([listing("a1", provider="alpha")], name="alpha")
    beta = FakeProvider([listing("b1", provider="beta")], name="beta")
    core = Bonneaffaire([alpha, beta], enabled=["alpha"])

    result = await core.search(keywords())

    assert [o.provider for o in result.outcomes] == ["alpha"]
    assert beta.queries == []
    with pytest.raises(UnknownProvider):
        await core.search(keywords(providers=["beta"]))


class FailingProvider:
    country = "FR"
    capabilities = Capabilities()

    def __init__(self, name: str, error: Exception) -> None:
        self.name = name
        self.error = error

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        raise self.error


class HangingProvider:
    name = "slow"
    country = "FR"
    capabilities = Capabilities()

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        await asyncio.sleep(60)
        return []


class ShapelessProvider:
    name = "shapeless"
    country = "FR"
    capabilities = Capabilities()

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        return [{"title": "not a Listing"}]  # ty: ignore[invalid-return-type]


async def test_failing_providers_are_reported_and_healthy_providers_listings_are_kept():
    healthy = FakeProvider([listing("ok1", provider="healthy")], name="healthy")
    core = Bonneaffaire(
        [
            healthy,
            FailingProvider("blocked", ProviderBlocked("blocked", "403 Forbidden")),
            FailingProvider("timeout", ProviderTimeout("timeout", "read timed out")),
            FailingProvider("shape", UnexpectedShape("shape", "no product cards")),
            FailingProvider("crash", KeyError("price")),
            HangingProvider(),
            ShapelessProvider(),
        ],
        timeout=0.05,
    )

    result = await core.search(keywords())

    assert [item.provider_id for item in result.listings] == ["ok1"]
    assert {o.provider: (o.status, o.listing_count) for o in result.outcomes} == {
        "healthy": (OutcomeStatus.OK, 1),
        "blocked": (OutcomeStatus.BLOCKED, 0),
        "timeout": (OutcomeStatus.TIMED_OUT, 0),
        "shape": (OutcomeStatus.FAILED, 0),
        "crash": (OutcomeStatus.FAILED, 0),
        "slow": (OutcomeStatus.TIMED_OUT, 0),
        "shapeless": (OutcomeStatus.FAILED, 0),
    }
    messages = {o.provider: o.message for o in result.outcomes}
    assert messages["blocked"] == "403 Forbidden"
    assert messages["shape"] == "no product cards"
    assert messages["healthy"] is None


async def test_an_empty_result_from_a_healthy_provider_is_ok_with_zero_listings():
    core = Bonneaffaire([FakeProvider([], name="empty")])

    result = await core.search(keywords())

    assert result.listings == []
    assert [(o.provider, o.status, o.listing_count) for o in result.outcomes] == [
        ("empty", OutcomeStatus.OK, 0)
    ]


async def test_providers_are_queried_concurrently():
    started: list[str] = []
    both_started = asyncio.Event()

    class WaitingProvider:
        country = "FR"
        capabilities = Capabilities()

        def __init__(self, name: str) -> None:
            self.name = name

        async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
            started.append(self.name)
            if len(started) == 2:
                both_started.set()
            await both_started.wait()
            return [listing(self.name, provider=self.name)]

    core = Bonneaffaire([WaitingProvider("alpha"), WaitingProvider("beta")], timeout=1)

    result = await core.search(keywords())

    assert [o.status for o in result.outcomes] == [OutcomeStatus.OK, OutcomeStatus.OK]


def euros(amount: int) -> Money:
    return Money(cents=amount * 100, currency="EUR")


def at(day: int) -> datetime:
    return datetime(2026, 11, day, 12, tzinfo=UTC)


async def test_merged_listings_sort_by_price_across_providers():
    alpha = FakeProvider(
        [listing("a120", price=euros(120)), listing("a80", price=euros(80))], name="alpha"
    )
    beta = FakeProvider(
        [listing("b95", price=euros(95)), listing("b60", price=euros(60))], name="beta"
    )
    core = Bonneaffaire([alpha, beta])

    result = await core.search(SearchRequest(query=SearchQuery(keywords="x", sort=Sort.PRICE)))

    assert [item.provider_id for item in result.listings] == ["b60", "a80", "b95", "a120"]


async def test_merged_listings_sort_by_recency_newest_first_and_undated_last():
    alpha = FakeProvider(
        [listing("a3", posted_at=at(3)), listing("undated"), listing("a7", posted_at=at(7))],
        name="alpha",
    )
    beta = FakeProvider([listing("b5", posted_at=at(5))], name="beta")
    core = Bonneaffaire([alpha, beta])

    result = await core.search(SearchRequest(query=SearchQuery(keywords="x", sort=Sort.RECENCY)))

    assert [item.provider_id for item in result.listings] == ["a7", "b5", "a3", "undated"]
