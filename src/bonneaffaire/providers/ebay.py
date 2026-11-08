"""eBay, through the official Browse API (marketplace EBAY_FR) with OAuth client credentials."""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from selectolax.lexbor import LexborHTMLParser

from bonneaffaire.models import (
    Condition,
    FilterName,
    Listing,
    ListingDetails,
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

NAME = "ebay"
API_URL = "https://api.ebay.com"
TOKEN_URL = f"{API_URL}/identity/v1/oauth2/token"
SEARCH_URL = f"{API_URL}/buy/browse/v1/item_summary/search"
ITEM_URL = f"{API_URL}/buy/browse/v1/item"
SELLER_URL = "https://www.ebay.fr/usr"
EBAY_HOST = re.compile(r"(?:[a-z0-9-]+\.)*ebay\.(?:com|fr|de|it|es|co\.uk|be|ch|at|ie|nl|pl)")
ITEM_PATH = re.compile(r"/itm/(?:[^/]+/)?(\d+)/?$")
SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE = "EBAY_FR"
TIMEOUT_SECONDS = 15.0
MAX_PAGE_SIZE = 200
TOKEN_RENEWAL_MARGIN_SECONDS = 60
SORTS = {Sort.PRICE: "price", Sort.RECENCY: "newlyListed"}
"""eBay's price sort orders by price plus shipping; the core re-sorts merged Listings anyway."""

CONDITION_IDS: dict[Condition, frozenset[str]] = {
    Condition.NEW: frozenset({"1000"}),  # New
    # New other (open box, no packaging), New with defects, Like New: unused or as good as.
    Condition.LIKE_NEW: frozenset({"1500", "1750", "2750"}),
    # Certified, Excellent, Very Good, Good refurbished; Seller refurbished.
    Condition.REFURBISHED: frozenset({"2000", "2010", "2020", "2030", "2500"}),
    # Pre-owned excellent, Used, Pre-owned fair, Very Good, Good, Acceptable.
    Condition.USED: frozenset({"2990", "3000", "3010", "4000", "5000", "6000"}),
    Condition.FOR_PARTS: frozenset({"7000"}),  # For parts or not working
}
"""eBay condition IDs per Condition (developer.ebay.com, 'Item condition ID and name values')."""

CONDITIONS = {cid: condition for condition, ids in CONDITION_IDS.items() for cid in ids}

SELLER_KINDS = {"BUSINESS": SellerKind.PROFESSIONAL, "INDIVIDUAL": SellerKind.PRIVATE}


@dataclass(frozen=True)
class EbayCredentials:
    """An eBay developer application's production keys (App ID and Cert ID)."""

    client_id: str
    client_secret: str


class EbayProvider:
    name = NAME
    country = "FR"
    capabilities = Capabilities(
        native_filters=frozenset(
            {FilterName.PRICE_MIN, FilterName.PRICE_MAX, FilterName.CONDITION, FilterName.SORT}
        ),
        listing_details=True,
    )

    def __init__(
        self,
        credentials: EbayCredentials,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._credentials = credentials
        self._client = client
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        body = await self._api_get(SEARCH_URL, search_params(query, limit))
        items = body.get("itemSummaries", [])
        if not isinstance(items, list):
            raise UnexpectedShape(NAME, "itemSummaries is not a list")
        listings = [self._listing(item) for item in items]
        if query.conditions:
            listings = [item for item in listings if item.condition in query.conditions]
        return listings[:limit]

    def listing_id_from_url(self, url: str) -> str | None:
        """eBay item pages are /itm/<legacy id> (optionally /itm/<slug>/<legacy id>)."""
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not EBAY_HOST.fullmatch(host):
            return None
        match = ITEM_PATH.match(parsed.path)
        return f"v1|{match.group(1)}|0" if match else None

    async def get_listing(self, provider_id: str) -> ListingDetails:
        item = await self._api_get(f"{ITEM_URL}/{quote(provider_id, safe='')}", missing=provider_id)
        listing = self._listing(item)
        seller = item.get("seller") or {}
        username = seller.get("username")
        images = [item.get("image"), *(item.get("additionalImages") or [])]
        availabilities = item.get("estimatedAvailabilities") or [{}]
        extra = {
            key: item.get(field)
            for key, field in (
                ("condition_description", "conditionDescription"),
                ("brand", "brand"),
                ("mpn", "mpn"),
                ("gtin", "gtin"),
                ("category_path", "categoryPath"),
            )
            if item.get(field)
        }
        return ListingDetails(
            **listing.model_dump(exclude={"total_cost", "attributes"}),
            attributes={**listing.attributes, **extra},
            description=_html_text(item.get("description")) or item.get("shortDescription"),
            photos=[image["imageUrl"] for image in images if image and image.get("imageUrl")],
            seller=Seller(name=username, url=f"{SELLER_URL}/{username}" if username else None),
            availability=availabilities[0].get("estimatedAvailabilityStatus"),
        )

    def _listing(self, item: dict[str, Any]) -> Listing:
        try:
            item_id = item["itemId"]
            title = item["title"]
            url = item["itemWebUrl"]
        except KeyError as exc:
            raise UnexpectedShape(NAME, f"item without {exc.args[0]}") from None
        price = _money(item.get("price"))
        if price is None:
            raise UnexpectedShape(NAME, f"item {item_id} has no readable price")
        seller = item.get("seller") or {}
        condition_id = item.get("conditionId")
        return Listing(
            provider=NAME,
            provider_id=item_id,
            title=title,
            url=url,
            thumbnail=(item.get("image") or {}).get("imageUrl"),
            price=price,
            shipping=_shipping(item.get("shippingOptions")),
            condition=CONDITIONS.get(condition_id, Condition.UNKNOWN),
            condition_label=item.get("condition"),
            seller_kind=SELLER_KINDS.get(seller.get("sellerAccountType"), SellerKind.UNKNOWN),
            location=_location(item.get("itemLocation")),
            posted_at=_datetime(item.get("itemCreationDate")),
            attributes={
                key: value
                for key, value in {
                    "condition_id": condition_id,
                    "buying_options": item.get("buyingOptions"),
                    "seller_username": seller.get("username"),
                }.items()
                if value
            },
        )

    async def _api_get(
        self, url: str, params: dict[str, str] | None = None, missing: str | None = None
    ) -> dict[str, Any]:
        """GET a Browse API resource; a rejected token is renewed and the call retried once.

        missing: the item ID, when a 404 means that Listing no longer exists.
        """
        for attempt in range(2):
            token = await self._access_token(renew=attempt > 0)
            headers = {"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE}
            response = await self._send("GET", url, params=params, headers=headers)
            if response.status_code != 401:
                break
        if missing is not None and response.status_code == 404:
            raise ListingNotFound(NAME, f"no item {missing}: {_error_text(response)}")
        _raise_for_status(response)
        return _json(response)

    async def _access_token(self, *, renew: bool = False) -> str:
        """The application token, fetched with client credentials and renewed before expiry."""
        if renew or self._token is None or self._clock() >= self._token_expires_at:
            response = await self._send(
                "POST",
                TOKEN_URL,
                data={"grant_type": "client_credentials", "scope": SCOPE},
                auth=(self._credentials.client_id, self._credentials.client_secret),
            )
            if response.status_code in (400, 401):
                raise ProviderError(NAME, f"eBay rejected the credentials: {_error_text(response)}")
            _raise_for_status(response)
            body = _json(response)
            token, lifetime = body.get("access_token"), body.get("expires_in")
            if not isinstance(token, str) or not isinstance(lifetime, int):
                raise UnexpectedShape(NAME, "token response without access_token/expires_in")
            self._token = token
            self._token_expires_at = self._clock() + lifetime - TOKEN_RENEWAL_MARGIN_SECONDS
        return self._token

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        client = self._client or httpx.AsyncClient()
        try:
            return await client.request(method, url, timeout=TIMEOUT_SECONDS, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(NAME, f"no answer from {url}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(NAME, f"request to {url} failed: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == 429:
        raise ProviderBlocked(NAME, f"rate limit reached (429): {_error_text(response)}")
    if status >= 400:
        raise ProviderError(NAME, f"HTTP {status}: {_error_text(response)}")


def _error_text(response: httpx.Response) -> str:
    """eBay's own explanation: Browse API `errors[].message` or OAuth `error_description`."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200] or response.reason_phrase
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list):
            messages = [str(e.get("message")) for e in errors if isinstance(e, dict)]
            if any(messages):
                return "; ".join(messages)
        if description := body.get("error_description") or body.get("error"):
            return str(description)
    return response.reason_phrase


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        raise UnexpectedShape(NAME, f"response from {response.url} is not JSON") from None
    if not isinstance(body, dict):
        raise UnexpectedShape(NAME, f"response from {response.url} is not a JSON object")
    return body


def search_params(query: SearchQuery, limit: int) -> dict[str, str]:
    """The item_summary/search query string: keywords plus the native Filters."""
    params = {"q": query.keywords or "", "limit": str(min(limit, MAX_PAGE_SIZE))}
    filters = []
    bounds = [bound for bound in (query.price_min, query.price_max) if bound is not None]
    if bounds:
        low = _decimal_text(query.price_min)
        high = _decimal_text(query.price_max)
        price_range = low if high is None else f"{low or ''}..{high}"
        filters += [f"price:[{price_range}]", f"priceCurrency:{bounds[0].currency}"]
    ids = sorted(cid for condition in query.conditions for cid in CONDITION_IDS.get(condition, ()))
    if ids:
        filters.append(f"conditionIds:{{{'|'.join(ids)}}}")
    if filters:
        params["filter"] = ",".join(filters)
    if query.sort is not None:
        params["sort"] = SORTS[query.sort]
    return params


def _decimal_text(money: Money | None) -> str | None:
    return None if money is None else f"{money.cents // 100}.{money.cents % 100:02d}"


def _money(value: object) -> Money | None:
    if not isinstance(value, dict):
        return None
    try:
        amount = Decimal(str(value["value"]))
    except KeyError, InvalidOperation:
        return None
    currency = value.get("currency")
    if not isinstance(currency, str):
        return None
    return Money(cents=int((amount * 100).to_integral_value()), currency=currency)


def _shipping(options: object) -> Money | None:
    """The cheapest known shipping cost; None when no option states one (e.g. CALCULATED)."""
    if not isinstance(options, list):
        return None
    costs = [cost for option in options if (cost := _money(option.get("shippingCost")))]
    return min(costs, key=lambda cost: cost.cents) if costs else None


def _location(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    parts = [value.get(key) for key in ("city", "postalCode", "country")]
    return ", ".join(part for part in parts if isinstance(part, str) and part) or None


BLOCK_END = re.compile(r"<br\s*/?>|</(?:p|div|li|tr|h[1-6])\s*>", re.IGNORECASE)


def _html_text(value: object) -> str | None:
    """The seller's HTML description as plain text, one line per block."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = LexborHTMLParser(BLOCK_END.sub("\n", value)).text(separator="")
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line) or None


def _datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def ebay(credentials: EbayCredentials, client: httpx.AsyncClient | None = None) -> EbayProvider:
    return EbayProvider(credentials, client=client)
