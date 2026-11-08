"""The core library: the single entry point the CLI and the MCP server adapt."""

from collections.abc import Iterable

from bonneaffaire.models import OutcomeStatus, ProviderOutcome, SearchRequest, SearchResult
from bonneaffaire.providers import Provider


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
