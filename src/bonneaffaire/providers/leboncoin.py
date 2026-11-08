"""Leboncoin, wrapping the maintained `lbc` library (anonymous access only).

`lbc` is synchronous (curl_cffi with browser impersonation), so calls run in a worker
thread, one at a time per Provider, on one reused session.
"""

import asyncio
import math
import re
from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

import httpx
import lbc
from curl_cffi import CurlError
from lbc.exceptions import (
    DatadomeError,
    LBCError,
    NotFoundError,
    ParseError,
    RequestTimeout,
)
from lbc.utils import build_search_payload_with_url
from pydantic import ValidationError

from bonneaffaire.models import (
    Condition,
    FilterName,
    Listing,
    ListingDetails,
    Location,
    Money,
    SearchQuery,
    Seller,
    SellerKind,
    Sort,
)
from bonneaffaire.providers import (
    Capabilities,
    ListingNotFound,
    ProviderBlocked,
    ProviderError,
    ProviderTimeout,
    UnexpectedShape,
)

NAME = "leboncoin"
CURRENCY = "EUR"
PARIS = ZoneInfo("Europe/Paris")
HOSTS = frozenset({"www.leboncoin.fr", "leboncoin.fr"})
AD_PATH = re.compile(r"^/(?:ad/)?[a-z_]+/(\d+)(?:\.htm)?/?$")
"""Ad pages: /ad/<category>/<id>, and the older /<category>/<id>.htm."""

CONDITIONS = {
    "etatneuf": Condition.NEW,
    "tresbonetat": Condition.LIKE_NEW,
    "bonetat": Condition.USED,
    "etatsatisfaisant": Condition.USED,
    "pourpieces": Condition.FOR_PARTS,
}
"""Leboncoin's `condition` attribute values; anything else is Unknown, label kept."""

SELLER_KINDS = {"private": SellerKind.PRIVATE, "pro": SellerKind.PROFESSIONAL}

SORTS = {Sort.PRICE: lbc.Sort.CHEAPEST, Sort.RECENCY: lbc.Sort.NEWEST}

GEOCODER_URL = "https://data.geopf.fr/geocodage/search"
"""The French national address API (Géoplateforme): turns a city or postcode into the
coordinates Leboncoin's location filter needs. Free, keyless, run by IGN."""

DEFAULT_RADIUS_METRES = 10_000
NO_MAX_EUROS = 1_000_000_000
"""lbc only takes a price range as (min, max); this stands in for 'no maximum'."""


def default_client() -> lbc.Client:
    # No retries: lbc re-opens a session on every 403, which DataDome reads as more abuse.
    return lbc.Client(timeout=15.0, max_retries=0)


class LeboncoinProvider:
    name = NAME
    country = "FR"

    def __init__(
        self,
        client_factory: Callable[[], lbc.Client] = default_client,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        """client_factory: builds the lbc client, once, on first use.
        http: client for geocoding places; a fresh one per lookup when None.
        """
        self._client_factory = client_factory
        self._client: lbc.Client | None = None
        self._lock = asyncio.Lock()
        self._http = http

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            native_filters=frozenset(
                {FilterName.PRICE_MIN, FilterName.PRICE_MAX, FilterName.LOCATION, FilterName.SORT}
            ),
            extras=frozenset({"category"}),
            native_urls=True,
            listing_details=True,
        )

    def recognises_native_url(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
        except ValueError:
            return False
        return (
            parts.scheme in {"http", "https"}
            and (parts.hostname or "") in HOSTS
            and parts.path.rstrip("/") == "/recherche"
        )

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        if query.native_url is not None:
            url = self._readable_native_url(query.native_url)
            return await self._search({"url": url, "limit": limit}, limit)
        options: dict[str, Any] = {"text": query.keywords, "limit": limit}
        extras = query.extras.get(self.name, {})
        if "category" in extras:
            options["category"] = self._category(extras["category"])
        if query.sort is not None:
            options["sort"] = SORTS[query.sort]
        if query.price_min is not None or query.price_max is not None:
            options["price"] = _euro_range(query.price_min, query.price_max)
        if query.location is not None:
            options["locations"] = await self._city(query.location)
        return await self._search(options, limit)

    def _readable_native_url(self, url: str) -> str:
        """The Native URL as lbc's URL reader needs it, checked before anything is sent.

        lbc splits the query on '&' and '=' without decoding it, so values are decoded
        here first, and the resulting search is built offline to catch what lbc can't read.
        """
        if not self.recognises_native_url(url):
            raise ProviderError(self.name, f"not a {self.name} Native URL: {url}")
        pairs = parse_qsl(urlsplit(url).query)
        decoded = "&".join(
            f"{key}={value}" for key, value in pairs if not {"&", "="} & set(key + value)
        )
        readable = f"https://www.leboncoin.fr/recherche?{decoded}"
        try:
            build_search_payload_with_url(readable)
        except (LBCError, LookupError, ValueError) as exc:
            raise ProviderError(self.name, f"unreadable Native URL {url}: {exc!r}") from exc
        return readable

    async def _search(self, options: dict[str, Any], limit: int) -> list[Listing]:
        result = await self._call(lambda client: client.search(**options))
        if result.total is None and not result.ads:
            raise UnexpectedShape(self.name, "search response has neither ads nor a total")
        listings = [self._listing(ad.raw) for ad in result.ads if _has_price(ad.raw)]
        if result.ads and not listings:
            raise UnexpectedShape(self.name, "no ad in the search response has a price_cents")
        return listings[:limit]

    def _category(self, value: str) -> lbc.Category:
        try:
            return lbc.Category(value) if value.isdigit() else lbc.Category[value.upper()]
        except KeyError, ValueError:
            raise ProviderError(self.name, f"unknown category {value!r}") from None

    async def _city(self, location: Location) -> lbc.City:
        client = self._http or httpx.AsyncClient()
        try:
            response = await client.get(
                GEOCODER_URL,
                params={
                    "q": location.place,
                    "index": "address",
                    "type": "municipality",
                    "limit": 1,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            features = response.json().get("features") or []
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(self.name, f"could not locate {location.place!r}: {exc}") from exc
        finally:
            if self._http is None:
                await client.aclose()
        if not features:
            raise ProviderError(self.name, f"no French town matches {location.place!r}")
        lng, lat = features[0]["geometry"]["coordinates"]
        radius = location.radius_km * 1000 if location.radius_km else DEFAULT_RADIUS_METRES
        name = features[0].get("properties", {}).get("city")
        return lbc.City(lat=lat, lng=lng, radius=radius, city=name)

    async def _call[T](self, operation: Callable[[lbc.Client], T]) -> T:
        async with self._lock:
            return await asyncio.to_thread(lambda: self._run(operation))

    def _run[T](self, operation: Callable[[lbc.Client], T]) -> T:
        """Run one lbc call, turning lbc's exceptions into ProviderErrors."""
        try:
            if self._client is None:
                self._client = self._client_factory()
            return operation(self._client)
        except DatadomeError as exc:
            raise ProviderBlocked(self.name, f"DataDome blocked the request: {exc}") from exc
        except RequestTimeout as exc:
            raise ProviderTimeout(self.name, str(exc)) from exc
        except NotFoundError as exc:
            raise ListingNotFound(self.name, str(exc)) from exc
        except ParseError as exc:
            raise UnexpectedShape(self.name, str(exc)) from exc
        except (LBCError, CurlError) as exc:
            raise ProviderError(self.name, str(exc)) from exc

    def listing_id_from_url(self, url: str) -> str | None:
        try:
            parts = urlsplit(url)
        except ValueError:
            return None
        if (parts.hostname or "") not in HOSTS:
            return None
        match = AD_PATH.search(parts.path)
        return match.group(1) if match else None

    async def get_listing(self, provider_id: str) -> ListingDetails:
        if not provider_id.isdigit():
            raise ListingNotFound(self.name, f"{provider_id!r} is not a Leboncoin ad ID")
        ad = await self._call(lambda client: client.get_ad(provider_id))
        raw = ad.raw
        if not _has_price(raw):
            raise UnexpectedShape(self.name, f"ad {provider_id} has no price_cents")
        owner = raw.get("owner") or {}
        favorites = (raw.get("counters") or {}).get("favorites")
        listing = self._listing(raw, extra_attributes={"favorites": favorites})
        try:
            return ListingDetails(
                **dict(listing),
                description=raw.get("body"),
                photos=list((raw.get("images") or {}).get("urls_large") or []),
                seller=Seller(name=owner.get("name")) if owner.get("name") else None,
            )
        except ValidationError as exc:
            raise UnexpectedShape(self.name, f"unreadable ad {provider_id}: {exc}") from exc

    def _listing(
        self, raw: dict[str, Any], extra_attributes: dict[str, Any] | None = None
    ) -> Listing:
        attributes = {
            item.get("key"): item for item in raw.get("attributes") or [] if isinstance(item, dict)
        }
        condition = attributes.get("condition") or {}
        owner = raw.get("owner") or {}
        location = raw.get("location") or {}
        images = raw.get("images") or {}
        kept = _raw_attributes(raw, attributes)
        kept.update({key: value for key, value in (extra_attributes or {}).items() if value})
        try:
            return Listing(
                provider=self.name,
                provider_id=str(raw["list_id"]),
                title=raw["subject"],
                url=raw["url"],
                price=Money(cents=raw["price_cents"], currency=CURRENCY),
                condition=CONDITIONS.get(condition.get("value", ""), Condition.UNKNOWN),
                condition_label=condition.get("value_label"),
                seller_kind=SELLER_KINDS.get(owner.get("type", ""), SellerKind.UNKNOWN),
                location=location.get("city_label"),
                thumbnail=images.get("thumb_url"),
                shipping=_cheapest_shipping(raw.get("shipping_fees")),
                posted_at=_paris_time(raw.get("first_publication_date")),
                attributes=kept,
            )
        except (KeyError, ValidationError) as exc:
            raise UnexpectedShape(self.name, f"unreadable ad {raw.get('list_id')}: {exc}") from exc


def _has_price(raw: dict[str, Any]) -> bool:
    """Ads without a price (gifts, 'prix sur demande') can't be Listings; they are skipped."""
    return isinstance(raw.get("price_cents"), int)


def _euro_range(low: Money | None, high: Money | None) -> list[int]:
    """Whole euros, rounded outward so no Listing inside the asked range is lost."""
    return [
        math.floor(low.cents / 100) if low else 0,
        math.ceil(high.cents / 100) if high else NO_MAX_EUROS,
    ]


def _cheapest_shipping(options: object) -> Money | None:
    """The cheapest delivery option the ad offers; None when it is hand delivery only."""
    if not isinstance(options, list):
        return None
    prices = [
        option["price"]
        for option in options
        if isinstance(option, dict) and isinstance(option.get("price"), int)
    ]
    return Money(cents=min(prices), currency=CURRENCY) if prices else None


def _paris_time(text: object) -> datetime | None:
    """Leboncoin dates are French wall-clock times like '2026-10-31 16:04:28'."""
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=PARIS)
    except ValueError:
        return None


def _raw_attributes(raw: dict[str, Any], attributes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    def label(key: str) -> Any:
        return (attributes.get(key) or {}).get("value_label")

    brand = next(
        (item.get("value_label") for key, item in attributes.items() if key.endswith("brand")),
        None,
    )
    buyer_fee = raw.get("buyer_fee") or {}
    candidates: dict[str, Any] = {
        "category": raw.get("category_name"),
        "category_id": raw.get("category_id"),
        "brand": brand,
        "condition_value": (attributes.get("condition") or {}).get("value"),
        "zipcode": (raw.get("location") or {}).get("zipcode"),
        "department": (raw.get("location") or {}).get("department_name"),
        "shipping_types": (attributes.get("shipping_type") or {}).get("values"),
        "shippable": label("shippable") == "true" if "shippable" in attributes else None,
        "quoted_buyer_fee_cents": buyer_fee.get("amount"),
        "owner_name": (raw.get("owner") or {}).get("name"),
        "status": raw.get("status"),
    }
    return {key: value for key, value in candidates.items() if value not in (None, "", [])}


def leboncoin(
    client_factory: Callable[[], lbc.Client] = default_client,
    http: httpx.AsyncClient | None = None,
) -> LeboncoinProvider:
    return LeboncoinProvider(client_factory, http=http)
