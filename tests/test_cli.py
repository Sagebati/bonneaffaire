"""CLI smoke test: the adapter calls the core and serialises results."""

import json

from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import Condition, Listing, Location, Money, SearchQuery, SellerKind, Sort
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


def test_search_passes_every_filter_and_extras_to_the_core():
    provider = FakeProvider()
    app = make_app(lambda: Bonneaffaire([provider]))

    result = CliRunner().invoke(
        app,
        [
            "search",
            "disque",
            "--min-price",
            "100",
            "--max-price",
            "450.50",
            "--condition",
            "New",
            "--condition",
            "LikeNew",
            "--near",
            "Lyon",
            "--radius-km",
            "20",
            "--sort",
            "price_asc",
            "--extra",
            "fake.category=15",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    query = provider.asked[0][0]
    assert query.price_min == Money(cents=10000, currency="EUR")
    assert query.price_max == Money(cents=45050, currency="EUR")
    assert query.conditions == {Condition.NEW, Condition.LIKE_NEW}
    assert query.location == Location(place="Lyon", radius_km=20)
    assert query.sort == Sort.PRICE_ASC
    payload = json.loads(result.output)
    assert payload["filter_reports"] == [
        {
            "provider": "fake",
            "native": [],
            "local": ["price_min", "price_max", "condition", "sort"],
            "unapplied": ["location"],
            "ignored_extras": ["category"],
        }
    ]


def test_the_table_reports_how_each_provider_applied_the_filters():
    app = make_app(lambda: Bonneaffaire([FakeProvider()]))

    runner = CliRunner(env={"COLUMNS": "200"})
    result = runner.invoke(app, ["search", "disque", "--max-price", "500", "--near", "Lyon"])

    assert result.exit_code == 0, result.output
    assert "fake Filters: local price_max; not applied location" in result.output


def test_a_malformed_extra_is_rejected():
    app = make_app(lambda: Bonneaffaire([FakeProvider()]))

    result = CliRunner().invoke(app, ["search", "disque", "--extra", "category15"])

    assert result.exit_code == 2
    assert "provider.name=value" in result.output
