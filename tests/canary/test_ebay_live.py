"""Live canary: hits the real eBay Browse API. Run with `uv run pytest -m canary`.

Needs BONNEAFFAIRE_EBAY_CLIENT_ID and BONNEAFFAIRE_EBAY_CLIENT_SECRET; skipped without them.
"""

import os

import pytest

from bonneaffaire.models import Condition, Money, SearchQuery
from bonneaffaire.providers.ebay import EbayCredentials, ebay
from bonneaffaire.registry import EBAY_CLIENT_ID_VARIABLE, EBAY_CLIENT_SECRET_VARIABLE

pytestmark = pytest.mark.canary

CLIENT_ID = os.environ.get(EBAY_CLIENT_ID_VARIABLE, "")
CLIENT_SECRET = os.environ.get(EBAY_CLIENT_SECRET_VARIABLE, "")
requires_credentials = pytest.mark.skipif(
    not (CLIENT_ID and CLIENT_SECRET),
    reason=f"set {EBAY_CLIENT_ID_VARIABLE} and {EBAY_CLIENT_SECRET_VARIABLE} to run",
)


@requires_credentials
async def test_ebay_search_still_parses():
    provider = ebay(EbayCredentials(CLIENT_ID, CLIENT_SECRET))
    query = SearchQuery(
        keywords="disque dur 8 To",
        price_min=Money(cents=2000, currency="EUR"),
        conditions=frozenset({Condition.USED, Condition.NEW}),
    )

    listings = await provider.search(query, limit=50)

    assert listings, "a common query returned no Listings; the Browse API may have changed"
    assert all(listing.price.cents >= 2000 for listing in listings)
    assert {listing.condition for listing in listings} <= {Condition.USED, Condition.NEW}
    assert all("ebay." in listing.url for listing in listings)

    details = await provider.get_listing(listings[0].provider_id)

    assert details.price.cents > 0
    assert details.photos
