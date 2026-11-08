"""CLI `listing` command: a thin adapter over Get Listing."""

import json

from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import (
    Condition,
    Listing,
    ListingDetails,
    Money,
    SearchQuery,
    Seller,
    SellerKind,
)
from bonneaffaire.providers import Capabilities, ListingNotFound

DETAILS = ListingDetails(
    provider="shop",
    provider_id="PB1",
    title="IronWolf 8 To",
    url="https://shop.example/fiche/PB1.html",
    price=Money(cents=44995, currency="EUR"),
    condition=Condition.NEW,
    seller_kind=SellerKind.PROFESSIONAL,
    description="Disque dur 3.5 pour NAS",
    photos=["https://shop.example/1.jpg", "https://shop.example/2.jpg"],
    seller=Seller(name="Shop SA"),
    availability="InStock",
    attributes={"ean": "8719706009812"},
)


class FakeShop:
    name = "shop"
    country = "FR"
    capabilities = Capabilities(listing_details=True)

    def __init__(self, gone: bool = False) -> None:
        self.gone = gone
        self.asked: list[str] = []

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        return []

    def listing_id_from_url(self, url: str) -> str | None:
        return "PB1" if url == DETAILS.url else None

    async def get_listing(self, provider_id: str) -> ListingDetails:
        self.asked.append(provider_id)
        if self.gone:
            raise ListingNotFound("shop", f"no Listing {provider_id}")
        return DETAILS


def run(provider: FakeShop, *args: str):
    app = make_app(lambda: Bonneaffaire([provider]))
    return CliRunner(env={"COLUMNS": "200"}).invoke(app, ["listing", *args])


def test_listing_by_provider_and_id_prints_the_details():
    shop = FakeShop()

    result = run(shop, "shop", "PB1")

    assert result.exit_code == 0, result.output
    assert shop.asked == ["PB1"]
    for expected in (
        "IronWolf 8 To",
        "449.95 EUR",
        "Disque dur 3.5 pour NAS",
        "https://shop.example/2.jpg",
        "Shop SA",
        "InStock",
        "8719706009812",
    ):
        assert expected in result.output


def test_listing_by_url_prints_json_on_request():
    shop = FakeShop()

    result = run(shop, DETAILS.url, "--json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["listing"]["photos"] == DETAILS.photos
    assert payload["listing"]["attributes"] == {"ean": "8719706009812"}


def test_a_removed_listing_says_not_found_and_exits_non_zero():
    result = run(FakeShop(gone=True), "shop", "PB1")

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_a_provider_without_an_id_is_a_usage_error():
    result = run(FakeShop(), "shop")

    assert result.exit_code == 2
