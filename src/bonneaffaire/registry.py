"""Which Providers exist, and which are enabled in configuration."""

import os
from collections.abc import Mapping

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.providers import Provider
from bonneaffaire.providers.ldlc import ldlc

DISABLED_PROVIDERS_VARIABLE = "BONNEAFFAIRE_DISABLED_PROVIDERS"


def default_providers() -> list[Provider]:
    return [ldlc()]


def default_core(environ: Mapping[str, str] = os.environ) -> Bonneaffaire:
    """Build the core from configuration.

    BONNEAFFAIRE_DISABLED_PROVIDERS: comma-separated Provider names to switch off.
    """
    disabled = {name.strip() for name in environ.get(DISABLED_PROVIDERS_VARIABLE, "").split(",")}
    providers = default_providers()
    return Bonneaffaire(providers, enabled=[p.name for p in providers if p.name not in disabled])
