"""The shared vocabulary: Listings, Search requests and results (see GLOSSARY.md)."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

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


class Sort(StrEnum):
    RELEVANCE = "relevance"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    NEWEST = "newest"


class Location(BaseModel):
    """Where to look: a place (city or postcode), optionally with a radius around it."""

    model_config = ConfigDict(frozen=True)

    place: str
    radius_km: int | None = Field(default=None, gt=0)


class SearchQuery(BaseModel):
    """What one Provider is asked to search for: keywords plus the canonical Filters.

    `extras` maps a Provider name to its Provider-specific extras; each Provider only ever
    sees its own entry, and only the extras it declares. Native URLs (ticket 04) are added here.
    """

    model_config = ConfigDict(frozen=True)

    keywords: str
    price_min: Money | None = None
    price_max: Money | None = None
    conditions: frozenset[Condition] = frozenset()
    location: Location | None = None
    sort: Sort | None = None
    extras: dict[str, dict[str, str]] = Field(default_factory=dict)

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
    """A Search as the caller asks it: the query and how many Listings per Provider.

    Provider selection is added in ticket 02.
    """

    model_config = ConfigDict(frozen=True)

    query: SearchQuery
    limit: int = Field(default=DEFAULT_LIMIT, gt=0)


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


class SearchResult(BaseModel):
    listings: list[Listing]
    outcomes: list[ProviderOutcome]
    filter_reports: list[FilterReport] = Field(default_factory=list)
