"""Live canary: hits the real vinted.fr. Run with `uv run pytest -m canary`.

Catches endpoint changes like Vinted's October 2026 switch to `svc-catalogue`.
"""

import pytest

from bonneaffaire.models import SearchQuery
from bonneaffaire.providers.vinted import vinted

pytestmark = pytest.mark.canary


async def test_vinted_search_and_details_still_parse():
    provider = vinted()

    listings = await provider.search(SearchQuery(keywords="disque dur"), limit=20)

    assert listings, "a common query returned no Listings; the search endpoint may have changed"
    assert all(listing.price.cents > 0 for listing in listings)
    assert all(listing.buyer_fee is not None for listing in listings)
    assert any(listing.condition_label for listing in listings)

    details = await provider.get_listing(listings[0].provider_id)

    assert details.price.cents > 0
    assert details.buyer_fee is not None
    assert details.condition_label
    assert details.photos
