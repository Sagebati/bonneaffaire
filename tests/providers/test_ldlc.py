"""LDLC, fed recorded search pages (Seam 2)."""

from pathlib import Path

import httpx
import pytest

from bonneaffaire.models import Condition, Money, SearchQuery, SellerKind
from bonneaffaire.providers import ProviderBlocked, UnexpectedShape
from bonneaffaire.providers.ldlc import ldlc

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ldlc"
SEARCH_PAGE = (FIXTURES / "search-disque-dur-8-to.html").read_text()


def replay(pages: dict[str, str], status: int = 200) -> httpx.AsyncClient:
    """An HTTP client that answers recorded pages by URL and 404s anything else."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = pages.get(str(request.url))
        if body is None:
            return httpx.Response(404, text="not recorded")
        return httpx.Response(status, text=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


SEARCH_URL = "https://www.ldlc.com/recherche/disque%20dur%208%20To/"


async def test_keyword_search_returns_listings_from_the_search_page():
    provider = ldlc(client=replay({SEARCH_URL: SEARCH_PAGE}))

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)

    assert len(listings) == 19
    first = listings[0]
    assert first.provider == "ldlc"
    assert first.provider_id == "PB00281525"
    assert first.title == "Seagate IronWolf 8 To (ST8000VN004)"
    assert first.url == "https://www.ldlc.com/fiche/PB00281525.html"
    assert first.thumbnail == "https://media.ldlc.com/r150/ld/products/00/06/00/95/LD0006009503.jpg"
    assert first.price == Money(cents=44995, currency="EUR")
    assert first.condition == Condition.NEW
    assert first.condition_label == "Neuf"
    assert first.seller_kind == SellerKind.PROFESSIONAL
    assert first.shipping is None
    assert first.total_cost is None
    assert listings[-1].provider_id == "PB00699187"
    assert listings[-1].price == Money(cents=39995, currency="EUR")


async def test_limit_caps_the_number_of_listings():
    provider = ldlc(client=replay({SEARCH_URL: SEARCH_PAGE}))

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=5)

    assert [listing.provider_id for listing in listings][:1] == ["PB00281525"]
    assert len(listings) == 5


async def test_raw_attributes_keep_the_card_details():
    provider = ldlc(client=replay({SEARCH_URL: SEARCH_PAGE}))

    first = (await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=1))[0]

    assert first.attributes["description"] == (
        'Disque dur 3.5" 8 To 7200 RPM 256 Mo Serial ATA 6 Gb/s pour NAS (bulk)'
    )
    assert first.attributes["offer_id"] == "AR201911210089"


async def test_a_challenge_response_is_reported_as_blocked():
    provider = ldlc(client=replay({SEARCH_URL: "<html>captcha</html>"}, status=403))

    with pytest.raises(ProviderBlocked):
        await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)


async def test_a_card_without_a_readable_price_is_an_unexpected_shape():
    broken = SEARCH_PAGE.replace("449€<sup>95</sup>", "Prix sur demande", 1)
    provider = ldlc(client=replay({SEARCH_URL: broken}))

    with pytest.raises(UnexpectedShape):
        await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)


async def test_a_no_results_page_is_an_empty_search_not_a_failure():
    url = "https://www.ldlc.com/recherche/zzqxwvkjhgfd/"
    provider = ldlc(client=replay({url: (FIXTURES / "search-no-results.html").read_text()}))

    assert await provider.search(SearchQuery(keywords="zzqxwvkjhgfd"), limit=50) == []


async def test_a_page_with_neither_cards_nor_a_no_results_notice_is_an_unexpected_shape():
    provider = ldlc(client=replay({SEARCH_URL: "<html><body>Maintenance</body></html>"}))

    with pytest.raises(UnexpectedShape):
        await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)


def test_ldlc_declares_that_it_accepts_native_urls():
    assert ldlc().capabilities.native_urls is True


@pytest.mark.parametrize(
    "url",
    [
        "https://www.ldlc.com/recherche/disque%20dur%208%20To/",
        "https://www.ldlc.com/recherche/disque dur/",
        "http://ldlc.com/recherche/ssd/+fv121-19183.html",
        "https://www.ldlc.com/recherche/ssd/page2/?sort=1#top",
    ],
)
def test_ldlc_recognises_its_own_search_page_urls(url: str):
    assert ldlc().recognises_native_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.ldlc.com/fiche/PB00281525.html",
        "https://www.ldlc.com/",
        "https://www.leboncoin.fr/recherche?text=disque",
        "https://www.ldlc.com.evil.example/recherche/ssd/",
        "ftp://www.ldlc.com/recherche/ssd/",
        "not a url",
    ],
)
def test_ldlc_does_not_recognise_other_urls(url: str):
    assert not ldlc().recognises_native_url(url)


async def test_a_native_url_returns_the_same_listings_as_the_equivalent_keyword_search():
    provider = ldlc(client=replay({SEARCH_URL: SEARCH_PAGE}))

    by_keywords = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)
    by_url = await provider.search(SearchQuery(native_url=SEARCH_URL), limit=50)

    assert by_url == by_keywords
    assert len(by_url) == 19


async def test_a_native_url_is_fetched_as_given_without_its_fragment():
    filtered = "https://www.ldlc.com/recherche/disque%20dur%208%20To/+fv121-19183.html?sort=1"
    provider = ldlc(client=replay({filtered: SEARCH_PAGE}))

    listings = await provider.search(SearchQuery(native_url=f"{filtered}#listing"), limit=3)

    assert len(listings) == 3
    assert listings[0].provider_id == "PB00281525"
