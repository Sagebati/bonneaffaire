"""The core library: the single entry point the CLI and the MCP server adapt."""

from collections.abc import Iterable

from bonneaffaire.models import (
    OutcomeStatus,
    ProviderOutcome,
    SearchQuery,
    SearchRequest,
    SearchResult,
)
from bonneaffaire.providers import NativeUrlProvider, Provider


class UnrecognisedNativeUrl(ValueError):
    """No Provider recognises the Native URL a Search was given."""

    def __init__(self, url: str, providers: list[str]) -> None:
        accepting = ", ".join(providers) or "none"
        super().__init__(
            f"no Provider recognises the Native URL {url} "
            f"(Providers accepting Native URLs: {accepting})"
        )
        self.url = url


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
        for provider in self._providers_for(request.query):
            listings = (await provider.search(request.query, request.limit))[: request.limit]
            result.listings.extend(listings)
            result.outcomes.append(
                ProviderOutcome(
                    provider=provider.name, status=OutcomeStatus.OK, listing_count=len(listings)
                )
            )
        return result

    def _providers_for(self, query: SearchQuery) -> list[Provider]:
        """Every Provider for a keyword Search; only the one that recognises a Native URL."""
        url = query.native_url
        if url is None:
            return self.providers
        accepting = [
            provider
            for provider in self.providers
            if provider.capabilities.native_urls and isinstance(provider, NativeUrlProvider)
        ]
        for provider in accepting:
            if provider.recognises_native_url(url):
                return [provider]
        raise UnrecognisedNativeUrl(url, [provider.name for provider in accepting])
