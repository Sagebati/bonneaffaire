"""Configuration read from the environment: Providers, credentials and politeness."""

import pytest
from typer.testing import CliRunner

from bonneaffaire.cli import make_app
from bonneaffaire.core import UnknownProvider
from bonneaffaire.models import SearchQuery, SearchRequest
from bonneaffaire.politeness import Politeness
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
    core = default_core({"BONNEAFFAIRE_DISABLED_PROVIDERS": "ldlc"})

    result = await core.search(SearchRequest(query=SearchQuery(keywords="nas")))

    assert result.outcomes == []


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
