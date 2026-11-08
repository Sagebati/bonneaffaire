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


class Sort(StrEnum):
    """How merged Listings are ordered: cheapest Price first, or newest first."""

    PRICE = "price"
    RECENCY = "recency"


class SearchQuery(BaseModel):
    """What one Provider is asked to search for.

    Filters (ticket 03) and Native URLs (ticket 04) are added here.
    sort: the core sorts merged Listings after merging; None keeps Provider order.
    """

    model_config = ConfigDict(frozen=True)

    keywords: str
    sort: Sort | None = None


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
