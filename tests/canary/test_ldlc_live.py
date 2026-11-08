"""Live canary: hits the real LDLC site. Run with `uv run pytest -m canary`."""

import pytest

from bonneaffaire.models import Condition, SearchQuery
from bonneaffaire.providers.ldlc import ldlc

pytestmark = pytest.mark.canary


async def test_ldlc_search_still_parses():
    listings = await ldlc().search(SearchQuery(keywords="disque dur"), limit=50)

    assert listings, "a common query returned no Listings; the search page may have changed"
    assert all(listing.price.cents > 0 for listing in listings)
    assert all(listing.url.startswith("https://www.ldlc.com/fiche/") for listing in listings)
    assert {listing.condition for listing in listings} == {Condition.NEW}
