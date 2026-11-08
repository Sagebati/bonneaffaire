"""Throttling, caching and backoff at the core seam, with fake Providers and a fake clock."""

import asyncio

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import (
    Condition,
    Listing,
    ListingDetails,
    ListingRequest,
    ListingStatus,
    Money,
    OutcomeStatus,
    SearchQuery,
    SearchRequest,
    SellerKind,
)
from bonneaffaire.politeness import Politeness
from bonneaffaire.providers import Capabilities, ProviderBlocked


class FakeClock:
    """Time only moves when someone sleeps or the test advances it, so tests never wait."""

    def __init__(self) -> None:
        self.now_seconds = 0.0
        self.sleepers: list[float] = []

    def now(self) -> float:
        return self.now_seconds

    async def sleep(self, seconds: float) -> None:
        """Wake sleepers in time order: each waits until it is the earliest one left."""
        wake = self.now_seconds + seconds
        self.sleepers.append(wake)
        while True:
            await asyncio.sleep(0)
            if wake == min(self.sleepers):
                break
        self.sleepers.remove(wake)
        self.now_seconds = max(self.now_seconds, wake)

    def advance(self, seconds: float) -> None:
        self.now_seconds += seconds


class RecordingProvider:
    """Records when it was asked, by the fake clock; can be told to report blocked."""

    country = "FR"
    capabilities = Capabilities()

    def __init__(self, clock: FakeClock, name: str = "fake") -> None:
        self.name = name
        self.clock = clock
        self.asked_at: list[float] = []
        self.blocked = False

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        self.asked_at.append(self.clock.now())
        if self.blocked:
            raise ProviderBlocked(self.name, "HTTP 403")
        return [
            Listing(
                provider=self.name,
                provider_id=f"{query.keywords}-{len(self.asked_at)}",
                title=str(query.keywords),
                url=f"https://fake.example/{len(self.asked_at)}",
                price=Money(cents=1000, currency="EUR"),
                condition=Condition.USED,
                seller_kind=SellerKind.PRIVATE,
            )
        ]


def search(keywords: str) -> SearchRequest:
    return SearchRequest(query=SearchQuery(keywords=keywords))


async def test_concurrent_searches_never_exceed_a_providers_rate():
    clock = FakeClock()
    slow = RecordingProvider(clock, "slow")
    fast = RecordingProvider(clock, "fast")
    core = Bonneaffaire(
        [slow, fast],
        politeness=Politeness(rates={"slow": 30}, default_rate=120),
        clock=clock,
    )

    await asyncio.gather(*(core.search(search(f"q{n}")) for n in range(4)))

    assert slow.asked_at == [0.0, 2.0, 4.0, 6.0]
    assert fast.asked_at == [0.0, 0.5, 1.0, 1.5]


async def test_a_repeated_identical_search_within_the_cache_window_asks_no_provider():
    clock = FakeClock()
    provider = RecordingProvider(clock)
    core = Bonneaffaire([provider], politeness=Politeness(cache_seconds=60), clock=clock)

    first = await core.search(search("disque"))
    clock.advance(59)
    repeat = await core.search(search("disque"))

    assert provider.asked_at == [0.0]
    assert repeat == first


async def test_the_cache_expires_after_its_window_and_keys_on_the_whole_request():
    clock = FakeClock()
    provider = RecordingProvider(clock)
    core = Bonneaffaire([provider], politeness=Politeness(cache_seconds=60), clock=clock)

    await core.search(search("disque"))
    await core.search(search("ssd"))
    await core.search(SearchRequest(query=SearchQuery(keywords="disque"), limit=3))
    clock.advance(60)
    await core.search(search("disque"))

    assert provider.asked_at == [0.0, 0.0, 0.0, 60.0]


async def test_a_blocked_provider_is_skipped_and_reported_blocked_until_its_backoff_expires():
    clock = FakeClock()
    blocked = RecordingProvider(clock, "blocked")
    healthy = RecordingProvider(clock, "healthy")
    blocked.blocked = True
    core = Bonneaffaire([blocked, healthy], politeness=Politeness(backoff_seconds=300), clock=clock)

    first = await core.search(search("a"))
    clock.advance(299)
    during = await core.search(search("b"))
    blocked.blocked = False
    clock.advance(1)
    after = await core.search(search("c"))

    statuses = [
        {o.provider: o.status for o in result.outcomes} for result in (first, during, after)
    ]
    assert statuses == [
        {"blocked": OutcomeStatus.BLOCKED, "healthy": OutcomeStatus.OK},
        {"blocked": OutcomeStatus.BLOCKED, "healthy": OutcomeStatus.OK},
        {"blocked": OutcomeStatus.OK, "healthy": OutcomeStatus.OK},
    ]
    assert blocked.asked_at == [0.0, 300.0]
    assert "backing off" in str(during.outcomes[0].message)


class DetailsProvider(RecordingProvider):
    capabilities = Capabilities(listing_details=True)

    def listing_id_from_url(self, url: str) -> str | None:
        return None

    async def get_listing(self, provider_id: str) -> ListingDetails:
        self.asked_at.append(self.clock.now())
        if self.blocked:
            raise ProviderBlocked(self.name, "HTTP 403")
        return ListingDetails(
            provider=self.name,
            provider_id=provider_id,
            title="Disque",
            url=f"https://fake.example/{provider_id}",
            price=Money(cents=1000, currency="EUR"),
            condition=Condition.USED,
            seller_kind=SellerKind.PRIVATE,
        )


async def test_get_listing_shares_the_providers_throttle_and_backoff_with_search():
    clock = FakeClock()
    provider = DetailsProvider(clock)
    core = Bonneaffaire(
        [provider], politeness=Politeness(default_rate=60, backoff_seconds=300), clock=clock
    )
    details = ListingRequest(provider="fake", provider_id="PB1")

    await asyncio.gather(core.search(search("disque")), core.get_listing(details))
    provider.blocked = True
    blocked = await core.get_listing(details)
    provider.blocked = False
    during = await core.search(search("ssd"))

    assert provider.asked_at == [0.0, 1.0, 2.0]
    assert blocked.status is ListingStatus.BLOCKED
    assert during.outcomes[0].status is OutcomeStatus.BLOCKED
