"""Splitting a query's Filters between a Provider and the core, and applying the core's share."""

from bonneaffaire.models import FilterName, FilterReport, Listing, SearchQuery, Sort
from bonneaffaire.providers import Capabilities

LOCALLY_APPLICABLE = frozenset(
    {FilterName.PRICE_MIN, FilterName.PRICE_MAX, FilterName.CONDITION, FilterName.SORT}
)
"""Location is never applied locally: Listings carry free-text places, not coordinates."""


def plan(
    provider: str, capabilities: Capabilities, query: SearchQuery
) -> tuple[SearchQuery, FilterReport]:
    """Decide, for one Provider, which Filters it applies natively and which the core applies.

    Returns the query to hand that Provider, carrying only its own declared extras, and the
    Filter report for it.
    """
    report = FilterReport(provider=provider)
    for name in query.filters_set():
        if name in capabilities.native_filters:
            report.native.append(name)
        elif name in LOCALLY_APPLICABLE:
            report.local.append(name)
        else:
            report.unapplied.append(name)
    requested = query.extras.get(provider, {})
    accepted = {key: value for key, value in requested.items() if key in capabilities.extras}
    report.ignored_extras = [key for key in requested if key not in accepted]
    provider_query = query.model_copy(update={"extras": {provider: accepted} if accepted else {}})
    return provider_query, report


def apply_locally(
    listings: list[Listing], query: SearchQuery, report: FilterReport
) -> list[Listing]:
    """Keep the Listings that pass the Filters the report assigns to the core."""
    return [item for item in listings if all(_passes(item, query, f) for f in report.local)]


def _passes(item: Listing, query: SearchQuery, name: FilterName) -> bool:
    match name:
        case FilterName.PRICE_MIN if query.price_min is not None:
            return item.price.currency == query.price_min.currency and (
                item.price.cents >= query.price_min.cents
            )
        case FilterName.PRICE_MAX if query.price_max is not None:
            return item.price.currency == query.price_max.currency and (
                item.price.cents <= query.price_max.cents
            )
        case FilterName.CONDITION:
            return item.condition in query.conditions
        case _:
            return True


def sort_merged(listings: list[Listing], sort: Sort | None) -> list[Listing]:
    """Order the merged Listings of all Providers. Relevance keeps each Provider's own order."""
    match sort:
        case Sort.PRICE_ASC:
            return sorted(listings, key=lambda item: item.price.cents)
        case Sort.PRICE_DESC:
            return sorted(listings, key=lambda item: item.price.cents, reverse=True)
        case Sort.NEWEST:
            dated = [item for item in listings if item.posted_at is not None]
            undated = [item for item in listings if item.posted_at is None]
            return sorted(dated, key=lambda item: item.posted_at or 0, reverse=True) + undated
        case _:
            return listings
