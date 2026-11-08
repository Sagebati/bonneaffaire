"""The shared vocabulary: Listings, Search requests and results (see GLOSSARY.md)."""

from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

DEFAULT_LIMIT = 50


class Condition(StrEnum):
    NEW = "New"
    REFURBISHED = "Refurbished"
    LIKE_NEW = "LikeNew"
    USED = "Used"
    FOR_PARTS = "ForParts"
    UNKNOWN = "Unknown"


class SellerKind(StrEnum):
    PRIVATE = "Private"
    PROFESSIONAL = "Professional"
    UNKNOWN = "Unknown"


class Money(BaseModel):
    """An amount in integer cents with an ISO 4217 currency. Never converted."""

    model_config = ConfigDict(frozen=True)

    cents: int
    currency: str

    def __str__(self) -> str:
        return f"{self.cents // 100}.{self.cents % 100:02d} {self.currency}"


class Listing(BaseModel):
    """One offer on a Provider. Identity is (provider, provider_id)."""

    model_config = ConfigDict(frozen=True)

    provider: str
    provider_id: str
    title: str
    url: str
    thumbnail: str | None = None
    price: Money
    shipping: Money | None = None
    buyer_fee: Money | None = None
    condition: Condition
    condition_label: str | None = None
    seller_kind: SellerKind
    location: str | None = None
    posted_at: datetime | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def total_cost(self) -> Money | None:
        """Price + Shipping + Buyer fee, only when all three are known in one currency."""
        if self.shipping is None or self.buyer_fee is None:
            return None
        parts = (self.price, self.shipping, self.buyer_fee)
        if len({part.currency for part in parts}) != 1:
            return None
        return Money(cents=sum(part.cents for part in parts), currency=self.price.currency)


class FilterName(StrEnum):
    """The canonical Filters besides keywords, which every Provider takes natively."""

    PRICE_MIN = "price_min"
    PRICE_MAX = "price_max"
    CONDITION = "condition"
    LOCATION = "location"
    SORT = "sort"


class Seller(BaseModel):
    """Who sells a Listing, as far as the Provider says."""

    model_config = ConfigDict(frozen=True)

    name: str | None = None
    url: str | None = None


class ListingDetails(Listing):
    """A Listing plus what only its own page shows (from Get Listing)."""

    description: str | None = None
    photos: list[str] = Field(default_factory=list)
    seller: Seller | None = None
    availability: str | None = None
    """The Provider's stock state, e.g. schema.org's 'InStock' or 'OutOfStock'."""
    other_offers: list[Listing] = Field(default_factory=list)
    """On retailers, other offers for the same product, each its own Listing."""


class ListingRequest(BaseModel):
    """Which Listing to get: a Provider plus its Provider ID, or a Listing URL."""

    model_config = ConfigDict(frozen=True)

    provider: str | None = None
    provider_id: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def _one_way_to_name_the_listing(self) -> ListingRequest:
        if self.url is None and (self.provider is None or self.provider_id is None):
            raise ValueError("give a Listing URL, or a Provider and a Provider ID")
        return self


class ListingStatus(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"
    BLOCKED = "blocked"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class ListingResult(BaseModel):
    """What Get Listing returns: the details when status is ok, otherwise why not."""

    status: ListingStatus
    provider: str | None = None
    listing: ListingDetails | None = None
    message: str | None = None


class Sort(StrEnum):
    """How merged Listings are ordered: cheapest Price first, or newest first."""

    PRICE = "price"
    RECENCY = "recency"


class Location(BaseModel):
    """Where to look: a place (city or postcode), optionally with a radius around it."""

    model_config = ConfigDict(frozen=True)

    place: str
    radius_km: int | None = Field(default=None, gt=0)


class SearchQuery(BaseModel):
    """What one Provider is asked to search for: keywords plus Filters, or a Native URL.

    A Native URL is the whole Search request: it goes only to the Provider that recognises
    it, which runs the search the URL describes.
    sort: the core sorts merged Listings after merging; None keeps Provider order.
    extras: Provider name to its Provider-specific extras; each Provider only ever sees its
    own entry, and only the extras it declares.
    """

    model_config = ConfigDict(frozen=True)

    keywords: str | None = None
    native_url: str | None = None
    price_min: Money | None = None
    price_max: Money | None = None
    conditions: frozenset[Condition] = frozenset()
    location: Location | None = None
    sort: Sort | None = None
    extras: dict[str, dict[str, str]] = Field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        keywords: str | None = None,
        native_url: str | None = None,
        price_min: Money | None = None,
        price_max: Money | None = None,
        conditions: Iterable[Condition] | None = None,
        location: Location | None = None,
        sort: Sort | None = None,
        extras: Mapping[str, Mapping[str, str]] | None = None,
    ) -> SearchQuery:
        """The one way adapters build a query from their arguments: absent collections are
        empty, and every rule (keywords or Native URL, no Filters with a Native URL) holds."""
        return cls(
            keywords=keywords,
            native_url=native_url,
            price_min=price_min,
            price_max=price_max,
            conditions=frozenset(conditions or ()),
            location=location,
            sort=sort,
            extras={provider: dict(values) for provider, values in (extras or {}).items()},
        )

    @model_validator(mode="after")
    def _keywords_or_native_url(self) -> SearchQuery:
        if (self.keywords is None) == (self.native_url is None):
            raise ValueError("a Search takes keywords or a Native URL, exactly one of them")
        if self.native_url is not None and (self.filters_set() or self.extras):
            given = [str(name) for name in self.filters_set()] + (["extras"] if self.extras else [])
            raise ValueError(
                "a Native URL is the whole Search: it takes no Filters or extras "
                f"(got {', '.join(given)}); set them on the Provider's website instead"
            )
        return self

    def filters_set(self) -> list[FilterName]:
        """The canonical Filters this query uses, in FilterName order."""
        values = {
            FilterName.PRICE_MIN: self.price_min,
            FilterName.PRICE_MAX: self.price_max,
            FilterName.CONDITION: self.conditions or None,
            FilterName.LOCATION: self.location,
            FilterName.SORT: self.sort,
        }
        return [name for name, value in values.items() if value is not None]


class SearchRequest(BaseModel):
    """A Search as the caller asks it: the query, which Providers, how many Listings each.

    providers: names of the Providers to ask; None means every enabled Provider.
    limit: Listings per Provider; None means the core's configured default limit.
    """

    model_config = ConfigDict(frozen=True)

    query: SearchQuery
    limit: int | None = Field(default=None, gt=0)
    providers: frozenset[str] | None = None


class OutcomeStatus(StrEnum):
    OK = "ok"
    BLOCKED = "blocked"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


class ProviderOutcome(BaseModel):
    """What happened when one Provider was asked during a Search."""

    provider: str
    status: OutcomeStatus
    listing_count: int = 0
    message: str | None = None


class FilterReport(BaseModel):
    """How one Provider's Listings were filtered during a Search.

    native: Filters the Provider applied itself. local: Filters the core applied to the
    Provider's fetched Listings. unapplied: Filters nobody could apply (e.g. location without
    location data). ignored_extras: extras sent to this Provider that it does not declare.
    """

    provider: str
    native: list[FilterName] = Field(default_factory=list)
    local: list[FilterName] = Field(default_factory=list)
    unapplied: list[FilterName] = Field(default_factory=list)
    ignored_extras: list[str] = Field(default_factory=list)


class ProviderInfo(BaseModel):
    """One Provider as List Providers shows it: what it supports and whether it is enabled.

    native_filters: canonical Filters it applies itself; the core applies the others locally.
    native_urls: whether a Search can take a Native URL copied from its website.
    listing_details: whether Get Listing works for its Listings.
    extras: names of the Provider-specific extras it accepts.
    disabled_reason: why a disabled Provider is off, when known (e.g. missing credentials).
    """

    name: str
    country: str
    enabled: bool
    native_filters: list[FilterName]
    native_urls: bool
    listing_details: bool
    extras: list[str]
    disabled_reason: str | None = None


class SearchResult(BaseModel):
    listings: list[Listing]
    outcomes: list[ProviderOutcome]
    filter_reports: list[FilterReport] = Field(default_factory=list)
