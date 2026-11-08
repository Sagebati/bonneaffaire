"""Configuration read from the environment."""

import asyncio

import pytest

from bonneaffaire.models import Listing, OutcomeStatus, SearchQuery, SearchRequest
from bonneaffaire.politeness import Politeness
from bonneaffaire.providers import Capabilities
from bonneaffaire.registry import default_core, politeness_from


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

    def __init__(self, delay: float = 0.0) -> None:
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
        ("BONNEAFFAIRE_DEFAULT_LIMIT", "2.5"),
        ("BONNEAFFAIRE_DEFAULT_LIMIT", "0"),
    ],
)
def test_bad_core_settings_are_rejected_naming_the_variable(variable: str, value: str):
    with pytest.raises(ValueError, match=variable):
        default_core({variable: value}, providers=[SlowProvider()])
