"""Get Listing on the core, with fake Providers (Seam 1)."""

import pytest
from pydantic import ValidationError

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import (
    Condition,
    Listing,
    ListingDetails,
    ListingRequest,
    ListingStatus,
    Money,
    SearchQuery,
    SellerKind,
)
from bonneaffaire.providers import (
    Capabilities,
    ListingNotFound,
    ProviderBlocked,
    ProviderError,
    ProviderTimeout,
)

DETAILS = ListingDetails(
    provider="shop",
    provider_id="P1",
    title="IronWolf 8 To",
    url="https://shop.example/p/P1",
    price=Money(cents=44995, currency="EUR"),
    condition=Condition.NEW,
    seller_kind=SellerKind.PROFESSIONAL,
    description="Disque dur NAS",
    photos=["https://shop.example/P1.jpg"],
    attributes={"ean": "8719706009812"},
)


class DetailsProvider:
    name = "shop"
    country = "FR"
    capabilities = Capabilities(listing_details=True)

    def __init__(self, error: ProviderError | None = None) -> None:
        self.error = error
        self.asked: list[str] = []

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        return []

    def listing_id_from_url(self, url: str) -> str | None:
        prefix = "https://shop.example/p/"
        return url.removeprefix(prefix) if url.startswith(prefix) else None

    async def get_listing(self, provider_id: str) -> ListingDetails:
        self.asked.append(provider_id)
        if self.error is not None:
            raise self.error
        return DETAILS


class SearchOnlyProvider:
    name = "flea"
    country = "FR"
    capabilities = Capabilities()

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        return []


async def test_details_by_provider_and_id():
    shop = DetailsProvider()
    core = Bonneaffaire([shop, SearchOnlyProvider()])

    result = await core.get_listing(ListingRequest(provider="shop", provider_id="P1"))

    assert result.status == ListingStatus.OK
    assert result.provider == "shop"
    assert result.listing == DETAILS
    assert shop.asked == ["P1"]


async def test_details_by_listing_url_find_the_provider_that_recognises_it():
    shop = DetailsProvider()
    core = Bonneaffaire([SearchOnlyProvider(), shop])

    result = await core.get_listing(ListingRequest(url="https://shop.example/p/P1"))

    assert result.status == ListingStatus.OK
    assert result.provider == "shop"
    assert shop.asked == ["P1"]


async def test_a_removed_listing_is_not_found_not_a_failure():
    core = Bonneaffaire([DetailsProvider(error=ListingNotFound("shop", "gone"))])

    result = await core.get_listing(ListingRequest(provider="shop", provider_id="P1"))

    assert result.status == ListingStatus.NOT_FOUND
    assert result.listing is None


async def test_a_provider_without_listing_details_is_unsupported():
    core = Bonneaffaire([SearchOnlyProvider()])

    result = await core.get_listing(ListingRequest(provider="flea", provider_id="X"))

    assert result.status == ListingStatus.UNSUPPORTED
    assert result.message is not None
    assert "flea" in result.message


@pytest.mark.parametrize(
    "request_",
    [
        ListingRequest(provider="nowhere", provider_id="X"),
        ListingRequest(url="https://elsewhere.example/item/1"),
    ],
)
async def test_an_unknown_provider_or_unrecognised_url_is_unsupported(request_):
    core = Bonneaffaire([DetailsProvider(), SearchOnlyProvider()])

    result = await core.get_listing(request_)

    assert result.status == ListingStatus.UNSUPPORTED
    assert result.message


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ProviderBlocked("shop", "403"), ListingStatus.BLOCKED),
        (ProviderTimeout("shop", "slow"), ListingStatus.TIMED_OUT),
        (ProviderError("shop", "boom"), ListingStatus.FAILED),
    ],
)
async def test_other_provider_errors_become_a_status(error, status):
    core = Bonneaffaire([DetailsProvider(error=error)])

    result = await core.get_listing(ListingRequest(provider="shop", provider_id="P1"))

    assert result.status == status
    assert result.message == error.message


def test_a_request_needs_a_url_or_a_provider_and_id():
    with pytest.raises(ValidationError):
        ListingRequest(provider="shop")
    with pytest.raises(ValidationError):
        ListingRequest()
