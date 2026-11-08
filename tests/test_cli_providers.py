"""CLI providers and serve commands."""

import json
from collections.abc import Callable

from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import Bonneaffaire
from bonneaffaire.models import FilterName, Listing, SearchQuery
from bonneaffaire.providers import Capabilities


class FakeProvider:
    country = "FR"

    def __init__(self, name: str, capabilities: Capabilities) -> None:
        self.name = name
        self.capabilities = capabilities

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        return []


def core() -> Bonneaffaire:
    return Bonneaffaire(
        [
            FakeProvider(
                "shop",
                Capabilities(
                    native_filters=frozenset({FilterName.SORT}),
                    native_urls=True,
                    listing_details=True,
                    extras=frozenset({"category"}),
                ),
            ),
            FakeProvider("flea", Capabilities()),
        ],
        enabled=["shop"],
    )


def test_providers_prints_each_providers_capabilities():
    result = CliRunner(env={"COLUMNS": "200"}).invoke(make_app(core), ["providers"])

    assert result.exit_code == 0, result.output
    shop, flea = (
        line for line in result.output.splitlines() if line.split()[:1] in (["shop"], ["flea"])
    )
    assert shop.split() == ["shop", "FR", "enabled", "sort", "yes", "yes", "category"]
    assert flea.split() == ["flea", "FR", "disabled", "-", "no", "no", "-"]


def test_serve_starts_the_mcp_server_on_the_given_host_and_port():
    started: list[tuple[str, int]] = []

    def serve(host: str, port: int, core_factory: Callable[[], Bonneaffaire]) -> None:
        assert core_factory is core
        started.append((host, port))

    app = make_app(core, serve=serve)
    flags = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0", "--port", "9000"])
    defaults = CliRunner().invoke(app, ["serve"])
    from_env = CliRunner(env={"BONNEAFFAIRE_HOST": "::", "BONNEAFFAIRE_PORT": "8100"}).invoke(
        app, ["serve"]
    )

    assert (flags.exit_code, defaults.exit_code, from_env.exit_code) == (0, 0, 0)
    assert started == [("0.0.0.0", 9000), ("127.0.0.1", 8000), ("::", 8100)]


def test_providers_prints_json_on_request():
    result = CliRunner().invoke(make_app(core), ["providers", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0] == {
        "name": "shop",
        "country": "FR",
        "enabled": True,
        "native_filters": ["sort"],
        "native_urls": True,
        "listing_details": True,
        "extras": ["category"],
        "disabled_reason": None,
    }
