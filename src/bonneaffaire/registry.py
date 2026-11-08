"""Which Providers exist. Ticket 02 adds enabling and disabling them in configuration."""

from bonneaffaire.core import Bonneaffaire
from bonneaffaire.providers import Provider
from bonneaffaire.providers.ldlc import ldlc


def default_providers() -> list[Provider]:
    return [ldlc()]


def default_core() -> Bonneaffaire:
    return Bonneaffaire(default_providers())
