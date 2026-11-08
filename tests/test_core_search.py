"""The core Search, with fake Providers (Seam 1)."""

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import (
    Condition,
    Listing,
    Money,
    OutcomeStatus,
    SearchQuery,
    SearchRequest,
    SellerKind,
)
from bonneaffaire.providers import Capabilities


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
    name = "fake"
    country = "FR"
    capabilities = Capabilities()

    def __init__(self, listings: list[Listing]) -> None:
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
