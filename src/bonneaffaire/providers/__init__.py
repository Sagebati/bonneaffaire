"""The Provider interface: what every marketplace integration implements."""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from bonneaffaire.models import Listing, ListingDetails, SearchQuery


@dataclass(frozen=True)
class Capabilities:
    """What a Provider declares about itself, so the core and tools can adapt.

    native_filters: canonical Filter names the Provider applies itself (ticket 03).
    native_urls: whether it accepts Native URLs (ticket 04).
    listing_details: whether it can fetch full Listing details (ticket 05).
    extras: Provider-specific extras it accepts (ticket 03).
    """

    native_filters: frozenset[str] = field(default_factory=frozenset)
    native_urls: bool = False
    listing_details: bool = False
    extras: frozenset[str] = field(default_factory=frozenset)


@runtime_checkable
class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def country(self) -> str: ...

    @property
    def capabilities(self) -> Capabilities: ...

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        """Return at most `limit` Listings, or raise a ProviderError."""
        ...


@runtime_checkable
class ListingDetailsProvider(Provider, Protocol):
    """A Provider that declares `listing_details` also implements these."""

    def listing_id_from_url(self, url: str) -> str | None:
        """The Provider ID in one of this Provider's Listing URLs, or None if it isn't one."""
        ...

    async def get_listing(self, provider_id: str) -> ListingDetails:
        """Return full details, or raise ListingNotFound or another ProviderError."""
        ...


@runtime_checkable
class NativeUrlProvider(Provider, Protocol):
    """A Provider that accepts Native URLs (and declares `capabilities.native_urls`)."""

    def recognises_native_url(self, url: str) -> bool:
        """Whether `url` is a search page address from this Provider's own website."""
        ...


class ProviderError(Exception):
    """Base for the typed failures a Provider signals; the core maps them to Provider outcomes."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message


class ProviderBlocked(ProviderError):
    """The Provider refused us (anti-bot challenge, 403, 429)."""


class ProviderTimeout(ProviderError):
    """The Provider did not answer in time."""


class UnexpectedShape(ProviderError):
    """The response did not look like what the Provider integration expects."""


class ListingNotFound(ProviderError):
    """The Listing no longer exists on the Provider."""


__all__ = [
    "Capabilities",
    "ListingDetailsProvider",
    "ListingNotFound",
    "NativeUrlProvider",
    "Provider",
    "ProviderBlocked",
    "ProviderError",
    "ProviderTimeout",
    "UnexpectedShape",
]
