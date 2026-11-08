"""The shared vocabulary: Listings, Search requests and results (see GLOSSARY.md)."""

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


class SearchQuery(BaseModel):
    """What one Provider is asked to search for: keywords, or a Native URL.

    A Native URL is the whole Search request: it goes only to the Provider that recognises
    it, which runs the search the URL describes. Filters (ticket 03) are added here.
    sort: the core sorts merged Listings after merging; None keeps Provider order.
    """

    model_config = ConfigDict(frozen=True)

    keywords: str | None = None
    native_url: str | None = None
    sort: Sort | None = None

    @model_validator(mode="after")
    def _keywords_or_native_url(self) -> SearchQuery:
        if (self.keywords is None) == (self.native_url is None):
            raise ValueError("a Search takes keywords or a Native URL, exactly one of them")
        return self


class SearchRequest(BaseModel):
    """A Search as the caller asks it: the query, which Providers, how many Listings each.

    providers: names of the Providers to ask; None means every enabled Provider.
    """

    model_config = ConfigDict(frozen=True)

    query: SearchQuery
    limit: int = Field(default=DEFAULT_LIMIT, gt=0)
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


class SearchResult(BaseModel):
    listings: list[Listing]
    outcomes: list[ProviderOutcome]
