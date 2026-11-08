"""Configuration read from the environment: Providers, credentials and politeness."""

import asyncio

import pytest
from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import UnknownProvider
from bonneaffaire.models import Listing, OutcomeStatus, SearchQuery, SearchRequest
from bonneaffaire.politeness import Politeness
from bonneaffaire.providers import Capabilities
from bonneaffaire.registry import default_core, politeness_from

EBAY_KEYS = {
    "BONNEAFFAIRE_EBAY_CLIENT_ID": "my-app-id",
    "BONNEAFFAIRE_EBAY_CLIENT_SECRET": "my-cert-id",
}


def test_ebay_is_enabled_when_its_credentials_are_configured():
    core = default_core(EBAY_KEYS)

    assert "ebay" in [provider.name for provider in core.providers]
    assert "ebay" not in core.disabled


def test_without_credentials_ebay_is_disabled_with_the_reason():
    core = default_core({"BONNEAFFAIRE_EBAY_CLIENT_ID": "my-app-id"})

    assert "ebay" not in [provider.name for provider in core.providers]
    assert "BONNEAFFAIRE_EBAY_CLIENT_SECRET" in core.disabled["ebay"]


def test_providers_switched_off_in_configuration_say_so():
    core = default_core({**EBAY_KEYS, "BONNEAFFAIRE_DISABLED_PROVIDERS": "ebay"})

    assert "BONNEAFFAIRE_DISABLED_PROVIDERS" in core.disabled["ebay"]


async def test_a_search_without_ebay_credentials_still_runs_the_other_providers():
    others = [info.name for info in default_core({}).list_providers() if info.name != "ebay"]
    core = default_core({"BONNEAFFAIRE_DISABLED_PROVIDERS": ",".join(others)})

    result = await core.search(SearchRequest(query=SearchQuery(keywords="nas")))

    assert result.outcomes == [], "eBay without credentials is not asked, so nothing fails"


async def test_asking_a_disabled_provider_explains_why():
    core = default_core({})

    with pytest.raises(UnknownProvider) as raised:
        await core.search(
            SearchRequest(query=SearchQuery(keywords="nas"), providers=frozenset({"ebay"}))
        )

    assert "BONNEAFFAIRE_EBAY_CLIENT_ID" in str(raised.value)


def test_the_cli_explains_why_ebay_is_disabled():
    app = make_app(lambda: default_core({}))

    result = CliRunner().invoke(app, ["search", "nas", "--provider", "ebay"])

    assert result.exit_code == 2
    assert "BONNEAFFAIRE_EBAY_CLIENT_ID" in result.output


def test_list_providers_shows_ebay_disabled_with_the_reason():
    infos = {info.name: info for info in default_core({}).list_providers()}

    assert infos["ebay"].enabled is False
    assert infos["ebay"].native_filters == ["price_min", "price_max", "condition", "sort"]
    assert infos["ebay"].listing_details
    assert "BONNEAFFAIRE_EBAY_CLIENT_ID" in (infos["ebay"].disabled_reason or "")
    assert infos["ldlc"].disabled_reason is None


def test_the_cli_providers_command_says_why_ebay_is_disabled():
    app = make_app(lambda: default_core({}))

    result = CliRunner(env={"COLUMNS": "200"}).invoke(app, ["providers"])

    assert result.exit_code == 0, result.output
    assert "ebay: disabled, no eBay credentials" in result.output


def test_politeness_has_polite_defaults():
    assert politeness_from({}) == Politeness(
        rates={}, default_rate=20, cache_seconds=120, backoff_seconds=600
    )


def test_rates_cache_window_and_backoff_are_configurable():
    environ = {
        "BONNEAFFAIRE_RATE_PER_MINUTE": "6",
        "BONNEAFFAIRE_PROVIDER_RATES": "ldlc=30, leboncoin=2.5",
        "BONNEAFFAIRE_CACHE_SECONDS": "0",
        "BONNEAFFAIRE_BACKOFF_SECONDS": "1800",
    }

    assert politeness_from(environ) == Politeness(
        rates={"ldlc": 30, "leboncoin": 2.5},
        default_rate=6,
        cache_seconds=0,
        backoff_seconds=1800,
    )


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("BONNEAFFAIRE_RATE_PER_MINUTE", "fast"),
        ("BONNEAFFAIRE_RATE_PER_MINUTE", "0"),
        ("BONNEAFFAIRE_PROVIDER_RATES", "ldlc"),
        ("BONNEAFFAIRE_CACHE_SECONDS", "-1"),
    ],
)
def test_bad_values_are_rejected_naming_the_variable(variable: str, value: str):
    with pytest.raises(ValueError, match=variable):
        politeness_from({variable: value})


class SlowProvider:
    name = "slow"
    country = "FR"
    capabilities = Capabilities()

    def __init__(self, delay: float = 0.0, name: str = "slow") -> None:
        self.name = name
        self.delay = delay
        self.limits: list[int] = []

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        self.limits.append(limit)
        await asyncio.sleep(self.delay)
        return []


def keyword_search() -> SearchRequest:
    return SearchRequest(query=SearchQuery(keywords="disque dur"))


async def test_provider_timeout_is_configurable():
    core = default_core({"BONNEAFFAIRE_TIMEOUT_SECONDS": "0.01"}, providers=[SlowProvider(1)])

    result = await core.search(keyword_search())

    assert result.outcomes[0].status == OutcomeStatus.TIMED_OUT


async def test_each_provider_can_have_its_own_timeout_falling_back_to_the_default():
    environ = {"BONNEAFFAIRE_TIMEOUT_SECONDS": "5", "BONNEAFFAIRE_PROVIDER_TIMEOUTS": "slow=0.01"}
    core = default_core(environ, providers=[SlowProvider(0.2), SlowProvider(0.2, name="steady")])

    result = await core.search(keyword_search())

    assert {o.provider: o.status for o in result.outcomes} == {
        "slow": OutcomeStatus.TIMED_OUT,
        "steady": OutcomeStatus.OK,
    }
    assert "0.01s" in (result.outcomes[0].message or "")


async def test_default_limit_is_configurable_and_a_requested_limit_wins():
    provider = SlowProvider()
    environ = {"BONNEAFFAIRE_DEFAULT_LIMIT": "7", "BONNEAFFAIRE_RATE_PER_MINUTE": "6000"}
    core = default_core(environ, providers=[provider])

    await core.search(keyword_search())
    await core.search(SearchRequest(query=SearchQuery(keywords="ssd"), limit=3))

    assert provider.limits == [7, 3]


async def test_default_limit_is_fifty():
    provider = SlowProvider()

    await default_core({}, providers=[provider]).search(keyword_search())

    assert provider.limits == [50]


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("BONNEAFFAIRE_TIMEOUT_SECONDS", "0"),
        ("BONNEAFFAIRE_PROVIDER_TIMEOUTS", "ldlc"),
        ("BONNEAFFAIRE_PROVIDER_TIMEOUTS", "ldlc=0"),
        ("BONNEAFFAIRE_DEFAULT_LIMIT", "2.5"),
        ("BONNEAFFAIRE_DEFAULT_LIMIT", "0"),
    ],
)
def test_bad_core_settings_are_rejected_naming_the_variable(variable: str, value: str):
    with pytest.raises(ValueError, match=variable):
        default_core({variable: value}, providers=[SlowProvider()])
