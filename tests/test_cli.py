"""CLI smoke test: the adapter calls the core and serialises results."""

import json

from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import Condition, Listing, Money, SearchQuery, SellerKind
from bonneaffaire.providers import Capabilities

LISTING = Listing(
    provider="fake",
    provider_id="PB1",
    title="IronWolf 8 To",
    url="https://fake.example/PB1",
    price=Money(cents=44995, currency="EUR"),
    condition=Condition.NEW,
    condition_label="Neuf",
    seller_kind=SellerKind.PROFESSIONAL,
)


class FakeProvider:
    name = "fake"
    country = "FR"
    capabilities = Capabilities()

    def __init__(self) -> None:
        self.asked: list[tuple[SearchQuery, int]] = []

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        self.asked.append((query, limit))
        return [LISTING]


def test_search_prints_a_table_by_default():
    provider = FakeProvider()
    app = make_app(lambda: Bonneaffaire([provider]))

    runner = CliRunner(env={"COLUMNS": "200"})
    result = runner.invoke(app, ["search", "disque", "dur", "8", "To"])

    assert result.exit_code == 0, result.output
    assert "IronWolf 8 To" in result.output
    assert "449.95 EUR" in result.output
    assert "New" in result.output
    assert provider.asked == [(SearchQuery(keywords="disque dur 8 To"), 50)]


def test_search_prints_json_on_request():
    provider = FakeProvider()
    app = make_app(lambda: Bonneaffaire([provider]))

    result = CliRunner().invoke(app, ["search", "disque dur", "--json", "--limit", "5"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["listings"][0]["provider_id"] == "PB1"
    assert payload["listings"][0]["price"] == {"cents": 44995, "currency": "EUR"}
    assert payload["outcomes"] == [
        {"provider": "fake", "status": "ok", "listing_count": 1, "message": None}
    ]
    assert provider.asked[0][1] == 5


class FakeUrlProvider(FakeProvider):
    capabilities = Capabilities(native_urls=True)

    def recognises_native_url(self, url: str) -> bool:
        return url.startswith("https://fake.example/")


def test_search_accepts_a_native_url_instead_of_keywords():
    provider = FakeUrlProvider()
    app = make_app(lambda: Bonneaffaire([provider]))

    url = "https://fake.example/recherche/disque/"
    result = CliRunner().invoke(app, ["search", url, "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["listings"][0]["provider_id"] == "PB1"
    assert provider.asked == [(SearchQuery(native_url=url), 50)]


def test_an_unrecognised_native_url_is_reported_and_exits_non_zero():
    provider = FakeUrlProvider()
    app = make_app(lambda: Bonneaffaire([provider]))

    result = CliRunner().invoke(app, ["search", "https://elsewhere.example/x"])

    assert result.exit_code == 1
    assert "no Provider recognises the Native URL https://elsewhere.example/x" in result.output
    assert provider.asked == []
