"""The core library: the single entry point the CLI and the MCP server adapt."""

from collections.abc import Iterable
from typing import TypeIs

from bonneaffaire.models import (
    ListingRequest,
    ListingResult,
    ListingStatus,
    OutcomeStatus,
    ProviderOutcome,
    SearchRequest,
    SearchResult,
)
from bonneaffaire.providers import (
    ListingDetailsProvider,
    ListingNotFound,
    Provider,
    ProviderBlocked,
    ProviderError,
    ProviderTimeout,
)


class Bonneaffaire:
    def __init__(self, providers: Iterable[Provider]) -> None:
        self._providers = {provider.name: provider for provider in providers}

    @property
    def providers(self) -> list[Provider]:
        return list(self._providers.values())

    async def search(self, request: SearchRequest) -> SearchResult:
        """Run one Search.

        For now each Provider is asked in turn and ProviderErrors propagate. Ticket 02 turns
        this into a concurrent fan-out with timeouts that maps ProviderErrors to outcomes.
        """
        result = SearchResult(listings=[], outcomes=[])
        for provider in self.providers:
            listings = (await provider.search(request.query, request.limit))[: request.limit]
            result.listings.extend(listings)
            result.outcomes.append(
                ProviderOutcome(
                    provider=provider.name, status=OutcomeStatus.OK, listing_count=len(listings)
                )
            )
        return result

    async def get_listing(self, request: ListingRequest) -> ListingResult:
        """Get one Listing's full details. Never raises ProviderErrors; reports a status."""
        if request.url is not None:
            for provider in self._details_providers():
                provider_id = provider.listing_id_from_url(request.url)
                if provider_id is not None:
                    return await self._get_listing(provider, provider_id)
            return ListingResult(
                status=ListingStatus.UNSUPPORTED,
                message=f"no Provider with Listing details recognises {request.url}",
            )
        assert request.provider is not None and request.provider_id is not None
        provider = self._providers.get(request.provider)
        if provider is None:
            return ListingResult(
                status=ListingStatus.UNSUPPORTED, message=f"no Provider named {request.provider}"
            )
        if not _has_listing_details(provider):
            return ListingResult(
                status=ListingStatus.UNSUPPORTED,
                provider=provider.name,
                message=f"{provider.name} does not support Listing details",
            )
        return await self._get_listing(provider, request.provider_id)

    def _details_providers(self) -> list[ListingDetailsProvider]:
        return [p for p in self._providers.values() if _has_listing_details(p)]

    @staticmethod
    async def _get_listing(provider: ListingDetailsProvider, provider_id: str) -> ListingResult:
        try:
            listing = await provider.get_listing(provider_id)
        except ProviderError as exc:
            return ListingResult(
                status=next(
                    (s for kind, s in _LISTING_STATUSES.items() if isinstance(exc, kind)),
                    ListingStatus.FAILED,
                ),
                provider=provider.name,
                message=exc.message,
            )
        return ListingResult(status=ListingStatus.OK, provider=provider.name, listing=listing)


_LISTING_STATUSES: dict[type[ProviderError], ListingStatus] = {
    ListingNotFound: ListingStatus.NOT_FOUND,
    ProviderBlocked: ListingStatus.BLOCKED,
    ProviderTimeout: ListingStatus.TIMED_OUT,
}


def _has_listing_details(provider: Provider) -> TypeIs[ListingDetailsProvider]:
    return provider.capabilities.listing_details and isinstance(provider, ListingDetailsProvider)
