"""The core List Providers: every Provider and what it supports."""

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import FilterName, Listing, ProviderInfo, SearchQuery
from bonneaffaire.providers import Capabilities


class FakeProvider:
    country = "FR"

    def __init__(self, name: str, capabilities: Capabilities) -> None:
        self.name = name
        self.capabilities = capabilities

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        return []


def test_list_providers_reports_each_providers_capabilities_and_whether_it_is_enabled():
    rich = FakeProvider(
        "rich",
        Capabilities(
            native_filters=frozenset({FilterName.SORT, FilterName.PRICE_MAX}),
            native_urls=True,
            listing_details=True,
            extras=frozenset({"category"}),
        ),
    )
    plain = FakeProvider("plain", Capabilities())
    core = Bonneaffaire([rich, plain], enabled=["rich"])

    assert core.list_providers() == [
        ProviderInfo(
            name="rich",
            country="FR",
            enabled=True,
            native_filters=[FilterName.PRICE_MAX, FilterName.SORT],
            native_urls=True,
            listing_details=True,
            extras=["category"],
        ),
        ProviderInfo(
            name="plain",
            country="FR",
            enabled=False,
            native_filters=[],
            native_urls=False,
            listing_details=False,
            extras=[],
        ),
    ]


def test_disabled_providers_are_listed_but_never_searched():
    core = Bonneaffaire([FakeProvider("off", Capabilities())], enabled=[])

    assert [info.name for info in core.list_providers()] == ["off"]
    assert core.providers == []
