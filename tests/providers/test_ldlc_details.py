"""LDLC Listing details, fed a recorded product page (Seam 2)."""

from pathlib import Path

import httpx
import pytest

from bonneaffaire.models import Condition, Money, SellerKind
from bonneaffaire.providers import ListingNotFound, UnexpectedShape
from bonneaffaire.providers.ldlc import ldlc

FIXTURES = Path(__file__).parent.parent / "fixtures" / "ldlc"
PRODUCT_URL = "https://www.ldlc.com/fiche/PB00281525.html"
PRODUCT_PAGE = (FIXTURES / "product-PB00281525.html").read_text()


def replay(pages: dict[str, httpx.Response]) -> httpx.AsyncClient:
    """An HTTP client that answers recorded responses by URL and 404s anything else."""

    def handler(request: httpx.Request) -> httpx.Response:
        return pages.get(str(request.url)) or httpx.Response(404, text="not recorded")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_details_come_from_the_product_page_json_ld():
    provider = ldlc(client=replay({PRODUCT_URL: httpx.Response(200, text=PRODUCT_PAGE)}))

    details = await provider.get_listing("PB00281525")

    assert details.provider == "ldlc"
    assert details.provider_id == "PB00281525"
    assert details.title == "Seagate IronWolf 8 To (ST8000VN004)"
    assert details.url == PRODUCT_URL
    assert details.price == Money(cents=44995, currency="EUR")
    assert details.condition == Condition.NEW
    assert details.condition_label == "Neuf"
    assert details.seller_kind == SellerKind.PROFESSIONAL
    assert details.availability == "InStock"
    assert details.description is not None
    assert "8 To 7200 RPM 256 Mo Serial ATA 6 Gb/s pour NAS" in details.description
    assert details.photos == [
        "https://media.ldlc.com/r1600/ld/products/00/06/00/95/LD0006009503.jpg",
        "https://media.ldlc.com/r1600/ld/products/00/06/00/95/LD0006009504.jpg",
        "https://media.ldlc.com/r1600/ld/products/00/06/00/95/LD0006009505.jpg",
    ]
    assert details.thumbnail == details.photos[0]
    assert details.seller is not None
    assert (details.seller.name, details.seller.url) == ("LDLC", "https://www.ldlc.com/")
    assert details.attributes == {
        "ean": "8719706009812",
        "mpn": "ST8000VN004",
        "sku": "AR201911210089",
        "brand": "Seagate Technology",
        "rating": 4.5,
        "review_count": 130,
    }
    assert details.other_offers == []


def test_ldlc_declares_listing_details():
    assert ldlc().capabilities.listing_details is True


def test_a_listing_url_is_recognised_and_others_are_not():
    provider = ldlc()

    assert provider.listing_id_from_url(PRODUCT_URL) == "PB00281525"
    assert provider.listing_id_from_url("https://www.ldlc.com/recherche/disque/") is None
    assert provider.listing_id_from_url("https://example.com/fiche/PB00281525.html") is None


async def test_a_removed_listing_redirecting_home_is_not_found():
    missing = "https://www.ldlc.com/fiche/PB99999999.html"
    provider = ldlc(
        client=replay(
            {
                missing: httpx.Response(301, headers={"Location": "/"}),
                "https://www.ldlc.com/": httpx.Response(200, text="<html>Accueil</html>"),
            }
        )
    )

    with pytest.raises(ListingNotFound):
        await provider.get_listing("PB99999999")


async def test_a_404_product_page_is_not_found():
    provider = ldlc(client=replay({}))

    with pytest.raises(ListingNotFound):
        await provider.get_listing("PB00281525")


async def test_a_product_page_without_product_json_ld_is_an_unexpected_shape():
    broken = PRODUCT_PAGE.replace('"@type": "Product"', '"@type": "Thing"')
    provider = ldlc(client=replay({PRODUCT_URL: httpx.Response(200, text=broken)}))

    with pytest.raises(UnexpectedShape):
        await provider.get_listing("PB00281525")
