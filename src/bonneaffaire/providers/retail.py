"""The config-driven generic retail Provider.

A simple retail site is described by a RetailSite: how to build its search URL and which
CSS selectors pick Listings out of its server-rendered search page. If it also has a
product page URL, Listing details are read from the schema.org Product/Offer JSON-LD that
such pages carry, so a new retailer needs no details code of its own.
"""

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote, urldefrag, urljoin, urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from bonneaffaire.models import (
    Condition,
    Listing,
    ListingDetails,
    Money,
    SearchQuery,
    Seller,
    SellerKind,
)
from bonneaffaire.providers import (
    Capabilities,
    ListingNotFound,
    ProviderBlocked,
    ProviderError,
    ProviderTimeout,
    UnexpectedShape,
)

BLOCKED_STATUSES = frozenset({403, 429, 503})
GONE_STATUSES = frozenset({404, 410})
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)


@dataclass(frozen=True)
class Pick:
    """Select a value inside a card: the element's text, or one of its attributes."""

    selector: str
    attribute: str | None = None


@dataclass(frozen=True)
class SearchPage:
    """Where Listings sit on the search page."""

    card: str
    title: Pick
    link: Pick
    price: Pick
    thumbnail: Pick | None = None
    provider_id_pattern: str = r"(.+)"
    """Regex applied to the absolute Listing URL; group 1 is the Provider ID."""
    no_results_text: str | None = None
    """Text present on a page that legitimately has no Listings."""
    attributes: dict[str, Pick] = field(default_factory=dict)


@dataclass(frozen=True)
class RetailSite:
    name: str
    country: str
    base_url: str
    search_url: str
    """Template with a `{keywords}` placeholder, filled URL-encoded."""
    currency: str
    condition: Condition
    condition_label: str
    seller_kind: SellerKind
    search_page: SearchPage
    product_url: str | None = None
    """Template with a `{provider_id}` placeholder; set it to offer Listing details."""
    native_url_hosts: frozenset[str] = field(default_factory=frozenset)
    """Hosts whose search pages this site accepts as Native URLs; empty means none."""
    native_url_path_prefix: str = "/"
    """Path prefix that marks a search page on those hosts."""
    timeout_seconds: float = 15.0


class RetailProvider:
    def __init__(self, site: RetailSite, client: httpx.AsyncClient | None = None) -> None:
        self.site = site
        self._client = client

    @property
    def name(self) -> str:
        return self.site.name

    @property
    def country(self) -> str:
        return self.site.country

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            listing_details=self.site.product_url is not None,
            native_urls=bool(self.site.native_url_hosts),
        )

    def recognises_native_url(self, url: str) -> bool:
        try:
            parts = urlsplit(url)
        except ValueError:
            return False
        return (
            parts.scheme in {"http", "https"}
            and (parts.hostname or "") in self.site.native_url_hosts
            and parts.path.startswith(self.site.native_url_path_prefix)
        )

    async def search(self, query: SearchQuery, limit: int) -> list[Listing]:
        if query.native_url is not None:
            if not self.recognises_native_url(query.native_url):
                raise ProviderError(self.name, f"not a {self.name} Native URL: {query.native_url}")
            url = urldefrag(query.native_url).url
        else:
            url = self.site.search_url.format(keywords=quote(query.keywords or "", safe=""))
        html = await self._fetch(url)
        return self._parse_search_page(html)[:limit]

    def listing_id_from_url(self, url: str) -> str | None:
        if self.site.product_url is None:
            return None
        if urlsplit(url).netloc != urlsplit(self.site.base_url).netloc:
            return None
        match = re.search(self.site.search_page.provider_id_pattern, url)
        return match.group(1) if match else None

    async def get_listing(self, provider_id: str) -> ListingDetails:
        if self.site.product_url is None:
            raise ProviderError(self.name, "this Provider has no Listing details")
        url = self.site.product_url.format(provider_id=quote(provider_id, safe=""))
        response = await self._get(url)
        if response.status_code in GONE_STATUSES:
            raise ListingNotFound(self.name, f"no Listing {provider_id}")
        self._raise_for_status(response, url)
        product = find_json_ld_product(response.text)
        if product is None:
            if response.history:
                # Retailers send removed products to their home page or a category.
                raise ListingNotFound(self.name, f"{url} redirects to {response.url}")
            raise UnexpectedShape(self.name, f"no JSON-LD Product on {url}")
        return self._details(provider_id, url, product)

    def _details(self, provider_id: str, url: str, product: dict[str, Any]) -> ListingDetails:
        offer = _first(product.get("offers"))
        if not isinstance(offer, dict):
            raise UnexpectedShape(self.name, f"no JSON-LD offer on {url}")
        cents = json_ld_price_cents(offer.get("price"))
        if cents is None:
            raise UnexpectedShape(self.name, f"no readable JSON-LD price on {url}")
        title = product.get("name")
        if not isinstance(title, str) or not title.strip():
            raise UnexpectedShape(self.name, f"no JSON-LD product name on {url}")
        condition_term = _schema_term(offer.get("itemCondition"))
        condition = SCHEMA_CONDITIONS.get(condition_term or "", self.site.condition)
        photos = [image for image in map(_image_url, _as_list(product.get("image"))) if image]
        seller = offer.get("seller")
        return ListingDetails(
            provider=self.name,
            provider_id=provider_id,
            title=title.strip(),
            url=offer.get("url") or url,
            thumbnail=photos[0] if photos else None,
            price=Money(cents=cents, currency=offer.get("priceCurrency") or self.site.currency),
            condition=condition,
            condition_label=(
                self.site.condition_label if condition == self.site.condition else condition_term
            ),
            seller_kind=self.site.seller_kind,
            attributes=json_ld_attributes(product),
            description=product.get("description"),
            photos=photos,
            seller=(
                Seller(name=seller.get("name"), url=seller.get("url"))
                if isinstance(seller, dict)
                else None
            ),
            availability=_schema_term(offer.get("availability")),
        )

    async def _fetch(self, url: str) -> str:
        response = await self._get(url)
        self._raise_for_status(response, url)
        return response.text

    def _raise_for_status(self, response: httpx.Response, url: str) -> None:
        if response.status_code in BLOCKED_STATUSES:
            raise ProviderBlocked(self.name, f"HTTP {response.status_code} from {url}")
        if response.status_code != 200:
            raise ProviderError(self.name, f"HTTP {response.status_code} from {url}")

    async def _get(self, url: str) -> httpx.Response:
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"},
        )
        try:
            return await client.get(url, timeout=self.site.timeout_seconds, follow_redirects=True)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(self.name, f"no answer from {url}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"request to {url} failed: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()

    def _parse_search_page(self, html: str) -> list[Listing]:
        page = self.site.search_page
        tree = HTMLParser(html)
        cards = tree.css(page.card)
        if not cards:
            if page.no_results_text and page.no_results_text in (tree.text() or ""):
                return []
            raise UnexpectedShape(self.name, f"no '{page.card}' cards and no no-results notice")
        return [self._parse_card(card) for card in cards]

    def _parse_card(self, card: Node) -> Listing:
        page = self.site.search_page
        url = urljoin(self.site.base_url, self._require(card, page.link, "link"))
        match = re.search(page.provider_id_pattern, url)
        if match is None:
            raise UnexpectedShape(self.name, f"no Provider ID in {url}")
        thumbnail = self._pick(card, page.thumbnail) if page.thumbnail else None
        attributes: dict[str, Any] = {
            key: value
            for key, pick in page.attributes.items()
            if (value := self._pick(card, pick)) is not None
        }
        return Listing(
            provider=self.name,
            provider_id=match.group(1),
            title=self._require(card, page.title, "title"),
            url=url,
            thumbnail=urljoin(self.site.base_url, thumbnail) if thumbnail else None,
            price=self._price(self._require(card, page.price, "price")),
            condition=self.site.condition,
            condition_label=self.site.condition_label,
            seller_kind=self.site.seller_kind,
            attributes=attributes,
        )

    def _price(self, text: str) -> Money:
        cents = parse_price_cents(text)
        if cents is None:
            raise UnexpectedShape(self.name, f"unreadable price {text!r}")
        return Money(cents=cents, currency=self.site.currency)

    def _require(self, card: Node, pick: Pick, what: str) -> str:
        value = self._pick(card, pick)
        if not value:
            raise UnexpectedShape(self.name, f"card has no {what} at '{pick.selector}'")
        return value

    @staticmethod
    def _pick(card: Node, pick: Pick) -> str | None:
        node = card if pick.selector == ":self" else card.css_first(pick.selector)
        if node is None:
            return None
        if pick.attribute is not None:
            return node.attributes.get(pick.attribute)
        text = node.text(separator="", strip=False)
        return " ".join(text.split()) or None


_PRICE = re.compile(r"^(\d+)(?:[€,.](\d{1,2}))?€?$")


def parse_price_cents(text: str) -> int | None:
    """Read French retail prices like '449€95', '1 299,95 €' or '89€' as integer cents."""
    compact = re.sub(r"\s", "", text)
    match = _PRICE.match(compact)
    if match is None:
        return None
    euros, decimals = match.groups()
    return int(euros) * 100 + int((decimals or "0").ljust(2, "0"))


SCHEMA_CONDITIONS = {
    "NewCondition": Condition.NEW,
    "RefurbishedCondition": Condition.REFURBISHED,
    "UsedCondition": Condition.USED,
    "DamagedCondition": Condition.FOR_PARTS,
}

_JSON_LD = re.compile(
    r"<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I
)


def find_json_ld_product(html: str) -> dict[str, Any] | None:
    """The first schema.org Product in a page's JSON-LD blocks, if any."""
    for block in _JSON_LD.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        candidates = _as_list(data)
        for item in list(candidates):
            if isinstance(item, dict) and "@graph" in item:
                candidates.extend(_as_list(item["@graph"]))
        for item in candidates:
            if isinstance(item, dict) and "Product" in _as_list(item.get("@type")):
                return item
    return None


def json_ld_attributes(product: dict[str, Any]) -> dict[str, Any]:
    """Identifiers and ratings from a JSON-LD Product, under stable attribute names."""
    brand = product.get("brand")
    rating = product.get("aggregateRating")
    rating = rating if isinstance(rating, dict) else {}
    candidates: dict[str, Any] = {
        "ean": product.get("gtin13") or product.get("gtin"),
        "mpn": product.get("mpn"),
        "sku": product.get("sku"),
        "brand": brand.get("name") if isinstance(brand, dict) else brand,
        "rating": _number(rating.get("ratingValue")),
        "review_count": _whole_number(rating.get("reviewCount") or rating.get("ratingCount")),
    }
    return {key: value for key, value in candidates.items() if value not in (None, "")}


def json_ld_price_cents(value: object) -> int | None:
    """Read a JSON-LD price ('449.95', 449.95 or '449,95') as integer cents."""
    amount = _decimal(value)
    if amount is None or amount < 0:
        return None
    return int((amount * 100).quantize(Decimal(1)))


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _number(value: object) -> float | None:
    amount = _decimal(value)
    return float(amount) if amount is not None else None


def _whole_number(value: object) -> int | None:
    amount = _decimal(value)
    return int(amount) if amount is not None else None


def _schema_term(value: object) -> str | None:
    """'https://schema.org/InStock' -> 'InStock'."""
    if not isinstance(value, str) or not value:
        return None
    return value.rstrip("/").rsplit("/", 1)[-1]


def _image_url(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("url") or value.get("contentUrl")
    return value if isinstance(value, str) and value else None


def _as_list(value: object) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _first(value: object) -> Any:
    items = _as_list(value)
    return items[0] if items else None
