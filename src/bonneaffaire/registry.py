"""Which Providers exist, which are enabled, and how politely they are treated."""

import os
from collections.abc import Mapping

from bonneaffaire.core import DEFAULT_TIMEOUT, Bonneaffaire
from bonneaffaire.models import DEFAULT_LIMIT
from bonneaffaire.politeness import Politeness
from bonneaffaire.providers import Provider
from bonneaffaire.providers.ebay import EbayCredentials, ebay
from bonneaffaire.providers.ldlc import ldlc
from bonneaffaire.providers.leboncoin import leboncoin

DISABLED_PROVIDERS_VARIABLE = "BONNEAFFAIRE_DISABLED_PROVIDERS"
EBAY_CLIENT_ID_VARIABLE = "BONNEAFFAIRE_EBAY_CLIENT_ID"
EBAY_CLIENT_SECRET_VARIABLE = "BONNEAFFAIRE_EBAY_CLIENT_SECRET"
RATE_VARIABLE = "BONNEAFFAIRE_RATE_PER_MINUTE"
PROVIDER_RATES_VARIABLE = "BONNEAFFAIRE_PROVIDER_RATES"
CACHE_VARIABLE = "BONNEAFFAIRE_CACHE_SECONDS"
BACKOFF_VARIABLE = "BONNEAFFAIRE_BACKOFF_SECONDS"
TIMEOUT_VARIABLE = "BONNEAFFAIRE_TIMEOUT_SECONDS"
LIMIT_VARIABLE = "BONNEAFFAIRE_DEFAULT_LIMIT"

DEFAULT_RATE_PER_MINUTE = 20.0
DEFAULT_CACHE_SECONDS = 120.0
DEFAULT_BACKOFF_SECONDS = 600.0


def default_providers(
    environ: Mapping[str, str] = os.environ,
) -> tuple[list[Provider], dict[str, str]]:
    """Every Provider, and why those that cannot run with this configuration cannot."""
    unavailable: dict[str, str] = {}
    client_id = environ.get(EBAY_CLIENT_ID_VARIABLE, "").strip()
    client_secret = environ.get(EBAY_CLIENT_SECRET_VARIABLE, "").strip()
    credentials = EbayCredentials(client_id, client_secret) if client_id and client_secret else None
    if credentials is None:
        unavailable["ebay"] = (
            f"no eBay credentials: set {EBAY_CLIENT_ID_VARIABLE} and {EBAY_CLIENT_SECRET_VARIABLE}"
        )
    return [ldlc(), leboncoin(), ebay(credentials)], unavailable


def default_core(
    environ: Mapping[str, str] = os.environ, providers: list[Provider] | None = None
) -> Bonneaffaire:
    """Build the core from configuration.

    BONNEAFFAIRE_DISABLED_PROVIDERS: comma-separated Provider names to switch off.
    BONNEAFFAIRE_EBAY_CLIENT_ID, BONNEAFFAIRE_EBAY_CLIENT_SECRET: the eBay application's
    production App ID and Cert ID; eBay is disabled without them.
    BONNEAFFAIRE_TIMEOUT_SECONDS: seconds each Provider gets to answer (default 20).
    BONNEAFFAIRE_DEFAULT_LIMIT: Listings per Provider when a Search names no limit (default 50).
    Politeness variables: see `politeness_from`.
    providers: the known Providers; `default_providers(environ)` when None.
    """
    switched_off = {
        name.strip() for name in environ.get(DISABLED_PROVIDERS_VARIABLE, "").split(",")
    }
    if providers is None:
        providers, disabled = default_providers(environ)
    else:
        disabled = {}
    for provider in providers:
        if provider.name in switched_off:
            disabled[provider.name] = f"switched off in {DISABLED_PROVIDERS_VARIABLE}"
    return Bonneaffaire(
        providers,
        enabled=[p.name for p in providers if p.name not in disabled],
        disabled=disabled,
        timeout=_number(
            TIMEOUT_VARIABLE, environ.get(TIMEOUT_VARIABLE), DEFAULT_TIMEOUT, positive=True
        ),
        default_limit=_whole_number(LIMIT_VARIABLE, environ.get(LIMIT_VARIABLE), DEFAULT_LIMIT),
        politeness=politeness_from(environ),
    )


def politeness_from(environ: Mapping[str, str]) -> Politeness:
    """Read throttling, caching and backoff settings.

    BONNEAFFAIRE_RATE_PER_MINUTE: requests per minute to each Provider (default 20).
    BONNEAFFAIRE_PROVIDER_RATES: per-Provider overrides, e.g. "ldlc=30,leboncoin=5".
    BONNEAFFAIRE_CACHE_SECONDS: how long identical Searches are answered from cache
    (default 120; 0 disables the cache).
    BONNEAFFAIRE_BACKOFF_SECONDS: how long a blocked Provider is left alone (default 600).
    """
    rates: dict[str, float] = {}
    for entry in environ.get(PROVIDER_RATES_VARIABLE, "").split(","):
        if not entry.strip():
            continue
        name, sep, value = entry.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"{PROVIDER_RATES_VARIABLE}: expected name=rate, got {entry!r}")
        rates[name.strip()] = _number(PROVIDER_RATES_VARIABLE, value, positive=True)
    return Politeness(
        rates=rates,
        default_rate=_number(
            RATE_VARIABLE, environ.get(RATE_VARIABLE), DEFAULT_RATE_PER_MINUTE, positive=True
        ),
        cache_seconds=_number(CACHE_VARIABLE, environ.get(CACHE_VARIABLE), DEFAULT_CACHE_SECONDS),
        backoff_seconds=_number(
            BACKOFF_VARIABLE, environ.get(BACKOFF_VARIABLE), DEFAULT_BACKOFF_SECONDS
        ),
    )


def _number(
    variable: str, raw: str | None, default: float = 0.0, *, positive: bool = False
) -> float:
    """A non-negative number (strictly positive if `positive`), or `default` when unset."""
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{variable}: expected a number, got {raw!r}") from None
    if value < 0 or (positive and value == 0):
        bound = "positive" if positive else "zero or more"
        raise ValueError(f"{variable}: expected a number {bound}, got {raw!r}")
    return value


def _whole_number(variable: str, raw: str | None, default: int) -> int:
    """A strictly positive integer, or `default` when unset."""
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{variable}: expected a whole number, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{variable}: expected a whole number above zero, got {raw!r}")
    return value
