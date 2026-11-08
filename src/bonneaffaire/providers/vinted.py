"""Vinted, wrapping the `vinted_scraper` library (anonymous session, `svc-catalogue` search).

Search goes through the library's `svc-catalogue` endpoint. Each Listing carries Vinted's
buyer protection as its Buyer fee. Search results do not state Shipping, so Total cost is
only known from Listing details, where the item page gives the cheapest delivery price.
"""

import json
import re
from collections.abc import Awaitable
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
from vinted_scraper import AsyncVintedWrapper

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
from bonneaffaire.providers.retail import (
    find_json_ld_product,
    json_ld_attributes,
    json_ld_price_cents,
)

NAME = "vinted"
MAX_PER_PAGE = 96

CONDITION_LABELS = {
    "Neuf avec étiquette": Condition.NEW,
    "Neuf sans étiquette": Condition.NEW,
    "Très bon état": Condition.LIKE_NEW,
    "Bon état": Condition.USED,
    "Satisfaisant": Condition.USED,
}
"""Vinted's French condition labels; 'Très bon état' (barely used) counts as LikeNew."""

STATUS_IDS = (
    ("6", Condition.NEW),  # Neuf avec étiquette
    ("1", Condition.NEW),  # Neuf sans étiquette
    ("2", Condition.LIKE_NEW),  # Très bon état
    ("3", Condition.USED),  # Bon état
    ("4", Condition.USED),  # Satisfaisant
)
"""Vinted's status filter IDs (`attribute_ids[status]`), in the order we send them."""

ORDERS = {Sort.PRICE: "price_low_to_high", Sort.RECENCY: "newest_first"}
CURRENCY = "EUR"

NATIVE_URL_PARAMS = {
    "search_text": "search_text",
    "catalog[]": "attribute_ids[catalog]",
    "brand_ids[]": "attribute_ids[brand]",
    "size_ids[]": "attribute_ids[size]",
    "color_ids[]": "attribute_ids[color]",
    "material_ids[]": "attribute_ids[material]",
    "patterns_ids[]": "attribute_ids[patterns]",
    "status_ids[]": "attribute_ids[status]",
    "status[]": "attribute_ids[status]",
    "price_from": "price_from",
    "price_to": "price_to",
    "currency": "currency",
    "order": "order",
}
"""Website catalog URL parameters and the `svc-catalogue` parameters they become."""

BLOCKED_STATUSES = frozenset({403, 429})
GONE_STATUSES = frozenset({404, 410})


class StatusWatch(httpx.AsyncBaseTransport):
    """Passes requests through, remembering the last HTTP status.

    vinted_scraper reports every failure as a bare RuntimeError; the status it saw tells a
    block (Cloudflare or DataDome 403) apart from a missing Listing or a broken response.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.last_status: int | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.last_status = None
        response = await self._inner.handle_async_request(request)
        self.last_status = response.status_code
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


class VintedProvider:
    def __init__(
        self,
        *,
        domain: str = "www.vinted.fr",
        country: str = "FR",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = f"https://{domain}"
        self._hosts = frozenset({domain, domain.removeprefix("www.")})
        self._country = country
        self._watch = StatusWatch(transport or httpx.AsyncHTTPTransport())
        self._wrapper: AsyncVintedWrapper | None = None

    @property
    def name(self) -> str:
        return NAME

    @property
    def country(self) -> str:
        return self._country

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            native_filters=frozenset(
                {FilterName.PRICE_MIN, FilterName.PRICE_MAX, FilterName.CONDITION, FilterName.SORT}
            ),
            native_urls=True,
            listing_details=True,
        )

    def recognises_native_url(self, url: str) -> bool:
        parts = urlsplit(url)
        return (
            parts.scheme in ("http", "https")
            and parts.hostname in self._hosts
            and (parts.path.rstrip("/") == "/catalog" or parts.path.startswith("/catalog/"))
        )

    def listing_id_from_url(self, url: str) -> str | None:
        parts = urlsplit(url)
        match = _ITEM_PATH.match(parts.path)
        if parts.hostname not in self._hosts or match is None:
            return None
        return match.group(1)

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        if query.native_url is not None:
            params: dict[str, Any] | None = _native_url_params(query.native_url)
        else:
            params = _search_params(query)
        if params is None:
            return []
        params["page"] = 1
        params["per_page"] = min(limit, MAX_PER_PAGE)
        wrapper = await self._session()
        data = await self._call(wrapper.search(params))
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise UnexpectedShape(NAME, "search response has no 'items' list")
        return [self._listing(item) for item in items[:limit]]

    async def get_listing(self, provider_id: str) -> ListingDetails:
        wrapper = await self._session()
        html = await self._call(self._item_page(wrapper, provider_id))
        return self._details(provider_id, html)

    async def _session(self) -> AsyncVintedWrapper:
        """The anonymous session, fetched once from the landing page and then reused."""
        if self._wrapper is None:
            wrapper = AsyncVintedWrapper(self._base_url, config={"transport": self._watch})
            await self._call(wrapper.refresh_session(retries=1))
            self._wrapper = wrapper
        return self._wrapper

    async def _item_page(self, wrapper: AsyncVintedWrapper, provider_id: str) -> str:
        """The full item page.

        vinted_scraper's own `item()` reads only the page's <head> (OpenGraph tags: no
        price, condition, fees or seller), so the page is read through the wrapper's site
        client with its session headers instead.
        """
        response = await wrapper._client.get(
            f"/items/{provider_id}", headers=wrapper._build_page_headers()
        )
        if response.status_code != 200:
            raise RuntimeError(f"item page answered HTTP {response.status_code}")
        return response.text

    async def _call[T](self, call: Awaitable[T]) -> T:
        """Run a library call, turning its failures into typed Provider errors."""
        try:
            return await call
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(NAME, f"no answer in time: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(NAME, f"HTTP failure: {exc!r}") from exc
        except RuntimeError as exc:
            status = self._watch.last_status
            if status in BLOCKED_STATUSES:
                raise ProviderBlocked(NAME, f"refused with HTTP {status}") from exc
            if status in GONE_STATUSES:
                raise ListingNotFound(NAME, f"HTTP {status}") from exc
            raise UnexpectedShape(NAME, str(exc)) from exc

    def _listing(self, item: Any) -> Listing:
        try:
            label = _condition_label(item.get("item_box") or {})
            user = item.get("user") or {}
            return Listing(
                provider=NAME,
                provider_id=str(item["id"]),
                title=item["title"],
                url=_absolute(self._base_url, item["url"]),
                thumbnail=(item.get("photo") or {}).get("url"),
                price=_money(item["price"]),
                buyer_fee=_money(item["service_fee"]) if item.get("service_fee") else None,
                condition=CONDITION_LABELS.get(label or "", Condition.UNKNOWN),
                condition_label=label,
                seller_kind=_seller_kind(user.get("business")),
                attributes={"seller_id": str(user["id"])} if user.get("id") else {},
            )
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise UnexpectedShape(NAME, f"unreadable search item: {exc!r}") from exc

    def _details(self, provider_id: str, html: str) -> ListingDetails:
        product = find_json_ld_product(html)
        if product is None:
            raise UnexpectedShape(NAME, f"item {provider_id} page has no JSON-LD Product")
        offer = product.get("offers")
        offer = offer[0] if isinstance(offer, list) and offer else offer
        if not isinstance(offer, dict):
            raise UnexpectedShape(NAME, f"item {provider_id} JSON-LD Product has no offer")
        cents = json_ld_price_cents(offer.get("price"))
        currency = offer.get("priceCurrency")
        if cents is None or not isinstance(currency, str) or not product.get("name"):
            raise UnexpectedShape(NAME, f"item {provider_id} offer has no readable price")

        flight = _flight_data(html)
        plugins = _plugins(flight)
        details = _plugin_attributes(plugins.get("attributes"))
        label = details.pop("status", None)
        seller = plugins.get("user_info_header") or {}
        gallery = plugins.get("gallery") or {}
        photos = [
            photo["url"]
            for photo in gallery.get("photos") or []
            if isinstance(photo, dict) and photo.get("url")
        ]
        services = (_decode_after(flight, '"pricingServices":') or {}).get("services") or {}
        seller_id = gallery.get("seller_id")
        attributes: dict[str, Any] = {
            **json_ld_attributes(product),
            **{key: product[key] for key in ("category", "color") if product.get(key)},
            **details,
        }
        if seller_id:
            attributes["seller_id"] = str(seller_id)
        try:
            return ListingDetails(
                provider=NAME,
                provider_id=provider_id,
                title=product["name"],
                url=offer.get("url") or f"{self._base_url}/items/{provider_id}",
                thumbnail=photos[0] if photos else product.get("image"),
                price=Money(cents=cents, currency=currency),
                shipping=_service_price(services, "shipping"),
                buyer_fee=_service_price(services, "buyerProtection"),
                condition=CONDITION_LABELS.get(label or "", Condition.UNKNOWN),
                condition_label=label,
                seller_kind=_seller_kind(seller.get("business")),
                attributes=attributes,
                description=product.get("description"),
                photos=photos,
                seller=Seller(
                    name=seller.get("name"),
                    url=f"{self._base_url}/member/{seller_id}" if seller_id else None,
                ),
                availability=offer.get("availability"),
            )
        except (TypeError, ValueError) as exc:
            raise UnexpectedShape(NAME, f"item {provider_id}: {exc!r}") from exc


_ITEM_PATH = re.compile(r"^/items/(\d+)(?:-[^/]*)?/?$")
_FLIGHT_CHUNK = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)')
_PLUGIN_START = re.compile(r'\{"data":')
_DECODER = json.JSONDecoder()


def _flight_data(html: str) -> str:
    """The Next.js flight payload the item page streams in `self.__next_f.push` scripts."""
    return "".join(json.loads(f'"{chunk}"') for chunk in _FLIGHT_CHUNK.findall(html))


def _plugins(flight: str) -> dict[str, dict[str, Any]]:
    """The item page's plugins ({'data': ..., 'name': 'attributes', ...}) by name; first wins.

    A plugin is either inline or wrapped once more ({'data': {'data': ..., 'name': ...}}).
    """
    found: dict[str, dict[str, Any]] = {}
    for match in _PLUGIN_START.finditer(flight):
        try:
            value, _ = _DECODER.raw_decode(flight, match.start())
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
            continue
        plugin = value if "name" in value else value["data"]
        name, data = plugin.get("name"), plugin.get("data")
        if isinstance(name, str) and isinstance(data, dict):
            found.setdefault(name, data)
    return found


def _plugin_attributes(data: dict[str, Any] | None) -> dict[str, str]:
    """The 'Détails' attributes by code (status, size, material...), without brand or age."""
    result: dict[str, str] = {}
    for attribute in (data or {}).get("attributes") or []:
        if not isinstance(attribute, dict):
            continue
        code = attribute.get("code")
        value = (attribute.get("data") or {}).get("value")
        if (
            isinstance(code, str)
            and code not in ("upload_date", "brand")
            and isinstance(value, str)
        ):
            result[code] = value
    return result


def _decode_after(flight: str, marker: str) -> dict[str, Any] | None:
    start = flight.find(marker)
    if start < 0:
        return None
    try:
        value, _ = _DECODER.raw_decode(flight, start + len(marker))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _service_price(services: dict[str, Any], name: str) -> Money | None:
    """A pricing service's final price: buyer protection, or the cheapest shipping."""
    service = services.get(name)
    if not isinstance(service, dict) or not isinstance(service.get("finalPrice"), dict):
        return None
    if name == "shipping" and services.get("isPickUpOnly"):
        return None
    try:
        return _money(service["finalPrice"])
    except KeyError, ValueError:
        return None


def _search_params(query: SearchQuery) -> dict[str, Any] | None:
    """The `svc-catalogue` parameters for a query, or None when no Vinted item can match."""
    params: dict[str, Any] = {"search_text": query.keywords}
    for key, money in (("price_from", query.price_min), ("price_to", query.price_max)):
        if money is None:
            continue
        if money.currency != CURRENCY:
            return None
        params[key] = f"{money.cents // 100}.{money.cents % 100:02d}"
    if query.conditions:
        ids = [status for status, condition in STATUS_IDS if condition in query.conditions]
        if not ids:
            return None
        params["attribute_ids[status]"] = ",".join(ids)
    if query.sort is not None:
        params["order"] = ORDERS[query.sort]
    return params


def _native_url_params(url: str) -> dict[str, Any]:
    """Translate a vinted.fr catalog URL into `svc-catalogue` parameters."""
    parts = urlsplit(url)
    values: dict[str, list[str]] = {}
    for key, value in parse_qsl(parts.query):
        api_key = NATIVE_URL_PARAMS.get(key)
        if api_key is not None and value:
            values.setdefault(api_key, []).append(value)
    params: dict[str, Any] = {key: ",".join(found) for key, found in values.items()}
    category = parts.path.removeprefix("/catalog/").split("-", 1)[0]
    if parts.path.startswith("/catalog/") and category.isdigit():
        params["attribute_ids[catalog]"] = category
    return params


def _condition_label(item_box: dict[str, Any]) -> str | None:
    """The condition label among the card's second-line parts ('Taille unique · Bon état')."""
    parts = [part.strip() for part in str(item_box.get("second_line") or "").split("·")]
    for part in parts:
        if part in CONDITION_LABELS:
            return part
    return None


def _seller_kind(business: object) -> SellerKind:
    if business is True:
        return SellerKind.PROFESSIONAL
    if business is False:
        return SellerKind.PRIVATE
    return SellerKind.UNKNOWN


def _money(value: Any) -> Money:
    """Vinted amounts: {'amount': '10.00', 'currency_code': 'EUR'} (or 'currencyCode')."""
    currency = value.get("currency_code") or value.get("currencyCode")
    try:
        amount = Decimal(str(value["amount"]))
    except InvalidOperation as exc:
        raise ValueError(f"not an amount: {value['amount']!r}") from exc
    if not currency or not amount.is_finite():
        raise ValueError(f"not an amount: {value!r}")
    return Money(cents=int((amount * 100).quantize(Decimal(1))), currency=currency)


def _absolute(base_url: str, path: str) -> str:
    return path if path.startswith("http") else f"{base_url}{path}"


def vinted(transport: httpx.AsyncBaseTransport | None = None) -> VintedProvider:
    """Vinted France. `transport` replaces the network, for tests."""
    return VintedProvider(transport=transport)
