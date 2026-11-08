"""Leboncoin through the CLI and the core, fed recorded responses."""

import json

import httpx
from lbc_replay import AD_URL, SEARCH_URL, Recorded, ReplaySession, fixture, replaying_client
from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import Bonneaffaire
from bonneaffaire.providers.leboncoin import leboncoin
from bonneaffaire.registry import default_core

ANSWERS = {
    SEARCH_URL: Recorded(200, fixture("search-disque-dur-8-to.json")),
    AD_URL.format(3299313803): Recorded(200, fixture("ad-3299313803.json")),
}


def geocoder() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=fixture("geocode-lyon.json"))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(*arguments: str, answers: dict[str, Recorded] = ANSWERS):
    session = ReplaySession(answers)
    provider = leboncoin(client_factory=lambda: replaying_client(session), http=geocoder())
    app = make_app(lambda: Bonneaffaire([provider]))
    result = CliRunner().invoke(app, list(arguments))
    return result, session


def test_a_keyword_search_returns_leboncoin_listings():
    result, _ = run("search", "disque", "dur", "8", "To", "--json")

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["outcomes"] == [
        {"provider": "leboncoin", "status": "ok", "listing_count": 35, "message": None}
    ]
    assert payload["listings"][0]["provider"] == "leboncoin"
    assert payload["listings"][0]["price"] == {"cents": 25000, "currency": "EUR"}


def test_a_filtered_search_is_applied_by_leboncoin_itself():
    result, session = run(
        "search",
        "disque dur 8 To",
        "--near",
        "Lyon",
        "--radius-km",
        "30",
        "--max-price",
        "300",
        "--condition",
        "Used",
        "--extra",
        "leboncoin.category=83",
        "--json",
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    [report] = payload["filter_reports"]
    assert report["native"] == ["price_max", "location"]
    assert report["local"] == ["condition"]
    assert report["ignored_extras"] == []
    assert {listing["condition"] for listing in payload["listings"]} == {"Used"}
    [sent] = session.payloads()
    assert sent["filters"]["category"] == {"id": "83"}
    assert sent["filters"]["location"]["locations"][0]["area"]["radius"] == 30_000


def test_a_pasted_leboncoin_url_returns_leboncoin_listings():
    result, session = run(
        "search", "https://www.leboncoin.fr/recherche?text=disque%20dur&category=15", "--json"
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["outcomes"][0]["status"] == "ok"
    assert session.payloads()[0]["filters"]["category"] == {"id": "15"}


def test_a_datadome_block_shows_as_a_blocked_outcome():
    result, _ = run(
        "search",
        "disque dur",
        answers={SEARCH_URL: Recorded(403, fixture("datadome-403.json"))},
    )

    assert result.exit_code == 0, result.output
    assert "leboncoin: blocked" in result.output


def test_listing_details_for_a_leboncoin_url():
    result, _ = run(
        "listing", "https://www.leboncoin.fr/ad/accessoires_informatique/3299313803", "--json"
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["listing"]["seller"]["name"] == "Seller 053"


def test_leboncoin_is_a_default_provider():
    assert "leboncoin" in [provider.name for provider in default_core({}).providers]
