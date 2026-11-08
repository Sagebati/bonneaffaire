"""The core library: the single entry point the CLI and the MCP server adapt."""

import asyncio
from collections.abc import Iterable, Mapping
from typing import TypeIs

from bonneaffaire.filters import apply_locally, plan
from bonneaffaire.models import (
    DEFAULT_LIMIT,
    FilterName,
    Listing,
    ListingDetails,
    ListingRequest,
    ListingResult,
    ListingStatus,
    OutcomeStatus,
    ProviderInfo,
    ProviderOutcome,
    SearchQuery,
    SearchRequest,
    SearchResult,
    Sort,
)
from bonneaffaire.politeness import Clock, Guard, Politeness, SystemClock
from bonneaffaire.providers import (
    ListingDetailsProvider,
    ListingNotFound,
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
        disabled: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        timeouts: Mapping[str, float] | None = None,
        default_limit: int = DEFAULT_LIMIT,
        politeness: Politeness | None = None,
        clock: Clock | None = None,
    ) -> None:
        """enabled: names of the Providers to keep; None keeps them all. Others are ignored.

        disabled: Provider name to the reason it is off (e.g. missing credentials), reported
        when someone asks for it and by List Providers.
        timeout: seconds each Provider gets to answer one Search or Get Listing (throttling
        waits excluded).
        timeouts: Provider name to its own timeout, overriding `timeout` for that Provider.
        default_limit: Listings per Provider when a Search request names no limit.
        politeness: throttling, caching and backoff; the default switches them all off.
        clock: time source for politeness; the system clock by default.
        """
        keep = None if enabled is None else set(enabled)
        self._all = list(providers)
        self._providers = {
            provider.name: provider
            for provider in self._all
            if keep is None or provider.name in keep
        }
        self._disabled = dict(disabled or {})
        self._timeout = timeout
        self._timeouts = dict(timeouts or {})
        self._default_limit = default_limit
        self._guard = Guard(politeness or Politeness(), clock or SystemClock())

    @property
    def disabled(self) -> dict[str, str]:
        """Providers that exist but are switched off, with the reason for each."""
        return dict(self._disabled)

    @property
    def providers(self) -> list[Provider]:
        return list(self._providers.values())

    def list_providers(self) -> list[ProviderInfo]:
        """Every known Provider, enabled or not, with the capabilities it declares."""
        return [
            ProviderInfo(
                name=provider.name,
                country=provider.country,
                enabled=provider.name in self._providers,
                native_filters=[n for n in FilterName if n in provider.capabilities.native_filters],
                native_urls=provider.capabilities.native_urls,
                listing_details=provider.capabilities.listing_details,
                extras=sorted(provider.capabilities.extras),
                disabled_reason=None
                if provider.name in self._providers
                else self._disabled.get(provider.name),
            )
            for provider in self._all
        ]

    async def search(self, request: SearchRequest) -> SearchResult:
        """Run one Search: ask the selected Providers concurrently and merge what they return.

        A Provider that fails never fails the Search: it gets a non-ok Provider outcome and the
        other Providers' Listings are kept.
        """
        providers = self._providers_for(request.query, self._select(request.providers))
        plans = [
            plan(provider.name, provider.capabilities, request.query) for provider in providers
        ]
        limit = self._default_limit if request.limit is None else request.limit
        answers = await asyncio.gather(
            *(
                self._ask(provider, query, limit)
                for provider, (query, _) in zip(providers, plans, strict=True)
            )
        )
        result = SearchResult(listings=[], outcomes=[], filter_reports=[r for _, r in plans])
        for (listings, outcome), (_, report) in zip(answers, plans, strict=True):
            listings = apply_locally(listings, request.query, report)
            outcome.listing_count = len(listings)
            result.listings.extend(listings)
            result.outcomes.append(outcome)
        if request.query.sort is not None:
            result.listings = sort_listings(result.listings, request.query.sort)
        return result

    async def get_listing(self, request: ListingRequest) -> ListingResult:
        """Get one Listing's full details. A Provider failing never raises; it reports a status."""
        if request.url is not None:
            for provider in self.providers:
                if not _has_listing_details(provider):
                    continue
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
                status=ListingStatus.UNSUPPORTED,
                message=f"no enabled Provider named {request.provider}",
            )
        if not _has_listing_details(provider):
            return ListingResult(
                status=ListingStatus.UNSUPPORTED,
                provider=provider.name,
                message=f"{provider.name} does not support Listing details",
            )
        return await self._get_listing(provider, request.provider_id)

    async def _get_listing(
        self, provider: ListingDetailsProvider, provider_id: str
    ) -> ListingResult:
        timeout = self._timeout_for(provider)

        async def fetch() -> ListingDetails:
            async with asyncio.timeout(timeout):
                return await provider.get_listing(provider_id)

        try:
            listing = await self._guard.request(provider.name, fetch)
        except Exception as exc:
            status, message = _failure(exc, timeout)
            return ListingResult(status=status, provider=provider.name, message=message)
        return ListingResult(status=ListingStatus.OK, provider=provider.name, listing=listing)

    async def _ask(
        self, provider: Provider, query: SearchQuery, limit: int
    ) -> tuple[list[Listing], ProviderOutcome]:
        def outcome(
            status: OutcomeStatus, message: str | None = None, count: int = 0
        ) -> ProviderOutcome:
            return ProviderOutcome(
                provider=provider.name, status=status, listing_count=count, message=message
            )

        timeout = self._timeout_for(provider)

        async def ask() -> list[Listing]:
            async with asyncio.timeout(timeout):
                return await provider.search(query, limit)

        try:
            answer = await self._guard.request(provider.name, ask, key=_cache_key(query, limit))
        except Exception as exc:
            status, message = _failure(exc, timeout)
            # A Search has no Listing to be missing: not found is that Provider's failure.
            return [], outcome(OUTCOME_STATUSES.get(status, OutcomeStatus.FAILED), message)
        if not isinstance(answer, list) or not all(
            isinstance(listing, Listing) for listing in answer
        ):
            return [], outcome(OutcomeStatus.FAILED, "unexpected response shape")
        listings = answer[:limit]
        return listings, outcome(OutcomeStatus.OK, count=len(listings))

    def _timeout_for(self, provider: Provider) -> float:
        return self._timeouts.get(provider.name, self._timeout)

    def _select(self, names: frozenset[str] | None) -> list[Provider]:
        if names is None:
            return self.providers
        unknown = names - self._providers.keys()
        if unknown:
            raise UnknownProvider(sorted(unknown), self._disabled)
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


OUTCOME_STATUSES = {
    ListingStatus.BLOCKED: OutcomeStatus.BLOCKED,
    ListingStatus.TIMED_OUT: OutcomeStatus.TIMED_OUT,
    ListingStatus.FAILED: OutcomeStatus.FAILED,
}


def _failure(exc: Exception, timeout: float) -> tuple[ListingStatus, str]:
    """The status and message for anything a Provider raised. Any exception that is not a
    ProviderError is a Provider bug, and so that Provider's failure, never the caller's."""
    match exc:
        case ListingNotFound():
            return ListingStatus.NOT_FOUND, exc.message
        case ProviderBlocked():
            return ListingStatus.BLOCKED, exc.message
        case ProviderTimeout():
            return ListingStatus.TIMED_OUT, exc.message
        case ProviderError():
            return ListingStatus.FAILED, exc.message
        case TimeoutError():
            return ListingStatus.TIMED_OUT, f"no answer within {timeout}s"
        case _:
            return ListingStatus.FAILED, f"{type(exc).__name__}: {exc}"


def _cache_key(query: SearchQuery, limit: int) -> str:
    """The normalised request one Provider is asked: the whole query it receives (keywords or
    Native URL, Filters, sort, extras) and the limit. Each Provider caches its own answers."""
    return f"{limit}:{query.model_dump_json()}"


def _has_listing_details(provider: Provider) -> TypeIs[ListingDetailsProvider]:
    return provider.capabilities.listing_details and isinstance(provider, ListingDetailsProvider)


def sort_listings(listings: list[Listing], order: Sort) -> list[Listing]:
    """Price: cheapest first (cents compared as-is, never converted). Recency: newest first,
    undated last. Both are stable, so ties keep Provider order."""
    if order is Sort.PRICE:
        return sorted(listings, key=lambda listing: listing.price.cents)
    dated = [listing for listing in listings if listing.posted_at is not None]
    undated = [listing for listing in listings if listing.posted_at is None]
    return sorted(dated, key=lambda listing: listing.posted_at or 0, reverse=True) + undated


class UnknownProvider(ValueError):
    """The request names Providers that do not exist or are not enabled."""

    def __init__(self, names: list[str], reasons: Mapping[str, str] | None = None) -> None:
        reasons = reasons or {}
        described = [f"{name} ({reasons[name]})" if name in reasons else name for name in names]
        super().__init__(f"Unknown or disabled Providers: {', '.join(described)}")
        self.names = names
