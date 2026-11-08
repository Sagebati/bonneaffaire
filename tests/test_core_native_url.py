"""Native URL Searches at the core, with fake Providers (Seam 1)."""

import pytest

from bonneaffaire.core import Bonneaffaire, UnrecognisedNativeUrl
from bonneaffaire.models import (
    Condition,
    Listing,
    Location,
    Money,
    OutcomeStatus,
    SearchQuery,
    SearchRequest,
    SellerKind,
    Sort,
)
from bonneaffaire.providers import Capabilities


def listing(provider: str, provider_id: str) -> Listing:
    return Listing(
        provider=provider,
        provider_id=provider_id,
        title=f"Disque {provider_id}",
        url=f"https://{provider}.example/{provider_id}",
        price=Money(cents=10000, currency="EUR"),
        condition=Condition.USED,
        seller_kind=SellerKind.PRIVATE,
    )


class FakeUrlProvider:
    """A fake Provider that accepts Native URLs on its own host."""

    country = "FR"
    capabilities = Capabilities(native_urls=True)

    def __init__(self, name: str) -> None:
        self.name = name
        self.queries: list[SearchQuery] = []

    def recognises_native_url(self, url: str) -> bool:
        return url.startswith(f"https://{self.name}.example/")

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        self.queries.append(query)
        return [listing(self.name, "1")]


class FakeKeywordProvider:
    """A fake Provider that does not accept Native URLs."""

    name = "keywords-only"
    country = "FR"
    capabilities = Capabilities()

    def __init__(self) -> None:
        self.queries: list[SearchQuery] = []

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        self.queries.append(query)
        return [listing(self.name, "1")]


async def test_a_native_url_is_sent_only_to_the_provider_that_recognises_it():
    alpha, beta, keywords_only = (
        FakeUrlProvider("alpha"),
        FakeUrlProvider("beta"),
        FakeKeywordProvider(),
    )
    core = Bonneaffaire([alpha, beta, keywords_only])
    query = SearchQuery(native_url="https://beta.example/search?q=disque")

    result = await core.search(SearchRequest(query=query))

    assert beta.queries == [query]
    assert alpha.queries == []
    assert keywords_only.queries == []
    assert [(item.provider, item.provider_id) for item in result.listings] == [("beta", "1")]
    assert [(o.provider, o.status) for o in result.outcomes] == [("beta", OutcomeStatus.OK)]


async def test_a_keyword_search_still_goes_to_every_provider():
    alpha, keywords_only = FakeUrlProvider("alpha"), FakeKeywordProvider()
    core = Bonneaffaire([alpha, keywords_only])

    result = await core.search(SearchRequest(query=SearchQuery(keywords="disque")))

    assert [o.provider for o in result.outcomes] == ["alpha", "keywords-only"]


async def test_an_unrecognised_native_url_is_a_clear_error():
    core = Bonneaffaire([FakeUrlProvider("alpha"), FakeKeywordProvider()])

    with pytest.raises(UnrecognisedNativeUrl, match=r"https://elsewhere\.example/x.*alpha"):
        await core.search(
            SearchRequest(query=SearchQuery(native_url="https://elsewhere.example/x"))
        )


def test_a_search_query_takes_keywords_or_a_native_url_but_not_both():
    with pytest.raises(ValueError, match="keywords or a Native URL"):
        SearchQuery(keywords="disque", native_url="https://alpha.example/x")
    with pytest.raises(ValueError, match="keywords or a Native URL"):
        SearchQuery()


@pytest.mark.parametrize(
    "filters",
    [
        {"price_min": Money(cents=1000, currency="EUR")},
        {"price_max": Money(cents=1000, currency="EUR")},
        {"conditions": frozenset({Condition.NEW})},
        {"location": Location(place="Lyon")},
        {"sort": Sort.PRICE},
        {"extras": {"alpha": {"category": "informatique"}}},
    ],
)
def test_a_native_url_takes_no_filters(filters):
    with pytest.raises(ValueError, match="Native URL is the whole Search"):
        SearchQuery(native_url="https://alpha.example/x", **filters)
