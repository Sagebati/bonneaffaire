"""Live canary: hits the real Leboncoin API. Run with `uv run pytest -m canary`.

Needs a French residential IP; from elsewhere DataDome usually blocks, which this reports
as a skip rather than a failure, since it says nothing about the response shape.
"""

import pytest

from bonneaffaire.models import SearchQuery
from bonneaffaire.providers import ProviderBlocked
from bonneaffaire.providers.leboncoin import leboncoin

pytestmark = pytest.mark.canary


async def test_leboncoin_search_and_details_still_parse():
    provider = leboncoin()
    try:
        listings = await provider.search(SearchQuery(keywords="disque dur"), limit=10)
        assert listings, "a common query returned no Listings; the API may have changed"
        assert all(listing.price.cents >= 0 for listing in listings)
        assert all(listing.url.startswith("https://www.leboncoin.fr/") for listing in listings)
        assert any(listing.condition_label for listing in listings)

        details = await provider.get_listing(listings[0].provider_id)
    except ProviderBlocked as exc:
        pytest.skip(f"blocked by DataDome: {exc}")

    assert details.provider_id == listings[0].provider_id
    assert details.description
