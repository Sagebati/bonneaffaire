"""Which Providers exist, and which are enabled in configuration."""

import os
from collections.abc import Mapping

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.providers import Provider
from bonneaffaire.providers.ebay import EbayCredentials, ebay
from bonneaffaire.providers.ldlc import ldlc

DISABLED_PROVIDERS_VARIABLE = "BONNEAFFAIRE_DISABLED_PROVIDERS"
EBAY_CLIENT_ID_VARIABLE = "BONNEAFFAIRE_EBAY_CLIENT_ID"
EBAY_CLIENT_SECRET_VARIABLE = "BONNEAFFAIRE_EBAY_CLIENT_SECRET"


def default_providers(
    environ: Mapping[str, str] = os.environ,
) -> tuple[list[Provider], dict[str, str]]:
    """The Providers that can run with this configuration, and why the others cannot."""
    providers: list[Provider] = [ldlc()]
    unavailable: dict[str, str] = {}
    client_id = environ.get(EBAY_CLIENT_ID_VARIABLE, "").strip()
    client_secret = environ.get(EBAY_CLIENT_SECRET_VARIABLE, "").strip()
    if client_id and client_secret:
        providers.append(ebay(EbayCredentials(client_id, client_secret)))
    else:
        unavailable["ebay"] = (
            f"no eBay credentials: set {EBAY_CLIENT_ID_VARIABLE} and {EBAY_CLIENT_SECRET_VARIABLE}"
        )
    return providers, unavailable


def default_core(environ: Mapping[str, str] = os.environ) -> Bonneaffaire:
    """Build the core from configuration.

    BONNEAFFAIRE_DISABLED_PROVIDERS: comma-separated Provider names to switch off.
    BONNEAFFAIRE_EBAY_CLIENT_ID, BONNEAFFAIRE_EBAY_CLIENT_SECRET: the eBay application's
    production App ID and Cert ID; eBay is disabled without them.
    """
    switched_off = {
        name.strip() for name in environ.get(DISABLED_PROVIDERS_VARIABLE, "").split(",")
    }
    providers, disabled = default_providers(environ)
    for provider in providers:
        if provider.name in switched_off:
            disabled[provider.name] = f"switched off in {DISABLED_PROVIDERS_VARIABLE}"
    return Bonneaffaire(
        providers,
        enabled=[p.name for p in providers if p.name not in disabled],
        disabled=disabled,
    )
