"""CLI smoke test: the adapter calls the core and serialises results."""

import json

from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import Condition, Listing, Money, SearchQuery, SellerKind
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

    assert [p.name for p in enabled.providers] == ["ldlc"]
    assert disabled.providers == []
