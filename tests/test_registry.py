"""Configuration read from the environment."""

import pytest

from bonneaffaire.politeness import Politeness
from bonneaffaire.registry import politeness_from


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
