"""The core library: the single entry point the CLI and the MCP server adapt."""

import asyncio
from collections.abc import Iterable

from bonneaffaire.models import (
    Listing,
    OutcomeStatus,
    ProviderOutcome,
    SearchQuery,
    SearchRequest,
    SearchResult,
    Sort,
)
from bonneaffaire.politeness import Clock, Guard, Politeness, SystemClock
from bonneaffaire.providers import (
    NativeUrlProvider,
    Provider,
    ProviderBlocked,
    ProviderError,
    ProviderTimeout,
)

DEFAULT_TIMEOUT = 20.0


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
    def __init__(
        self,
        providers: Iterable[Provider],
        *,
        enabled: Iterable[str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        politeness: Politeness | None = None,
        clock: Clock | None = None,
    ) -> None:
        """enabled: names of the Providers to keep; None keeps them all. Others are ignored.

        timeout: seconds each Provider gets to answer one Search (throttling waits excluded).
        politeness: throttling, caching and backoff; the default switches them all off.
        clock: time source for politeness; the system clock by default.
        """
        keep = None if enabled is None else set(enabled)
        self._providers = {
            provider.name: provider
            for provider in providers
            if keep is None or provider.name in keep
        }
        self._timeout = timeout
        self._guard = Guard(politeness or Politeness(), clock or SystemClock())

    @property
    def providers(self) -> list[Provider]:
        return list(self._providers.values())

    async def search(self, request: SearchRequest) -> SearchResult:
        """Run one Search: ask the selected Providers concurrently and merge what they return.

        A Provider that fails never fails the Search: it gets a non-ok Provider outcome and the
        other Providers' Listings are kept.
        """
        providers = self._providers_for(request.query, self._select(request.providers))
        answers = await asyncio.gather(*(self._ask(provider, request) for provider in providers))
        result = SearchResult(listings=[], outcomes=[])
        for listings, outcome in answers:
            result.listings.extend(listings)
            result.outcomes.append(outcome)
        if request.query.sort is not None:
            result.listings = sort_listings(result.listings, request.query.sort)
        return result

    async def _ask(
        self, provider: Provider, request: SearchRequest
    ) -> tuple[list[Listing], ProviderOutcome]:
        def outcome(
            status: OutcomeStatus, message: str | None = None, count: int = 0
        ) -> ProviderOutcome:
            return ProviderOutcome(
                provider=provider.name, status=status, listing_count=count, message=message
            )

        async def ask() -> list[Listing]:
            async with asyncio.timeout(self._timeout):
                return await provider.search(request.query, request.limit)

        try:
            answer = await self._guard.request(provider.name, ask, key=_cache_key(request))
        except ProviderBlocked as exc:
            return [], outcome(OutcomeStatus.BLOCKED, exc.message)
        except ProviderTimeout as exc:
            return [], outcome(OutcomeStatus.TIMED_OUT, exc.message)
        except TimeoutError:
            return [], outcome(OutcomeStatus.TIMED_OUT, f"no answer within {self._timeout}s")
        except ProviderError as exc:
            return [], outcome(OutcomeStatus.FAILED, exc.message)
        except Exception as exc:  # any Provider bug is that Provider's failure
            return [], outcome(OutcomeStatus.FAILED, f"{type(exc).__name__}: {exc}")
        if not isinstance(answer, list) or not all(isinstance(i, Listing) for i in answer):
            return [], outcome(OutcomeStatus.FAILED, "unexpected response shape")
        listings = answer[: request.limit]
        return listings, outcome(OutcomeStatus.OK, count=len(listings))

    def _select(self, names: frozenset[str] | None) -> list[Provider]:
        if names is None:
            return self.providers
        unknown = names - self._providers.keys()
        if unknown:
            raise UnknownProvider(sorted(unknown))
        return [provider for provider in self.providers if provider.name in names]

    def _providers_for(self, query: SearchQuery, selected: list[Provider]) -> list[Provider]:
        """Every selected Provider for a keyword Search; only the one that recognises a
        Native URL."""
        url = query.native_url
        if url is None:
            return selected
        accepting = [
            provider
            for provider in selected
            if provider.capabilities.native_urls and isinstance(provider, NativeUrlProvider)
        ]
        for provider in accepting:
            if provider.recognises_native_url(url):
                return [provider]
        raise UnrecognisedNativeUrl(url, [provider.name for provider in accepting])


def _cache_key(request: SearchRequest) -> str:
    """The normalised request one Provider is asked: the whole query (keywords or Native URL,
    Filters, sort) and the limit. Provider selection is left out: each Provider caches its
    own answers."""
    return request.model_dump_json(include={"query", "limit"})


def sort_listings(listings: list[Listing], order: Sort) -> list[Listing]:
    """Price: cheapest first (cents compared as-is, never converted). Recency: newest first,
    undated last. Both are stable, so ties keep Provider order."""
    if order is Sort.PRICE:
        return sorted(listings, key=lambda item: item.price.cents)
    dated = [item for item in listings if item.posted_at is not None]
    undated = [item for item in listings if item.posted_at is None]
    return sorted(dated, key=lambda item: item.posted_at or 0, reverse=True) + undated


class UnknownProvider(ValueError):
    """The request names Providers that do not exist or are not enabled."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(f"Unknown or disabled Providers: {', '.join(names)}")
        self.names = names
