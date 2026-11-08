"""CLI smoke test: the adapter calls the core and serialises results."""

import json

from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import Condition, Listing, Location, Money, SearchQuery, SellerKind, Sort
from bonneaffaire.providers import Capabilities, ProviderBlocked
from bonneaffaire.registry import default_core

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
            "price",
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
    assert query.sort == Sort.PRICE
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


class BlockedProvider:
    name = "blocked"
    country = "FR"
    capabilities = Capabilities()

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        raise ProviderBlocked(self.name, "403 Forbidden")


def test_search_shows_provider_outcomes_alongside_the_listings():
    app = make_app(lambda: Bonneaffaire([FakeProvider(), BlockedProvider()]))

    result = CliRunner(env={"COLUMNS": "200"}).invoke(app, ["search", "disque", "--sort", "price"])

    assert result.exit_code == 0, result.output
    assert "IronWolf 8 To" in result.output
    assert "fake: ok (1 Listings)" in result.output
    assert "blocked: blocked (0 Listings) 403 Forbidden" in result.output


def test_search_can_target_chosen_providers():
    fake = FakeProvider()
    app = make_app(lambda: Bonneaffaire([fake, BlockedProvider()]))

    result = CliRunner().invoke(app, ["search", "disque", "--provider", "fake", "--json"])

    assert result.exit_code == 0, result.output
    assert [o["provider"] for o in json.loads(result.output)["outcomes"]] == ["fake"]


def test_search_rejects_unknown_providers():
    app = make_app(lambda: Bonneaffaire([FakeProvider()]))

    result = CliRunner().invoke(app, ["search", "disque", "--provider", "nope"])

    assert result.exit_code == 2
    assert "nope" in result.output


def test_providers_can_be_disabled_in_configuration():
    enabled = default_core({})
    disabled = default_core({"BONNEAFFAIRE_DISABLED_PROVIDERS": "ldlc"})

    assert "ldlc" in [p.name for p in enabled.providers]
    assert "ldlc" not in [p.name for p in disabled.providers]


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
