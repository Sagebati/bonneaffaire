"""The config-driven generic retail Provider.

A simple retail site is described by a RetailSite: how to build its search URL and which
CSS selectors pick Listings out of its server-rendered search page. Product pages
(JSON-LD Product/Offer) are added with Listing details in ticket 05.
"""

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urldefrag, urljoin, urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from bonneaffaire.models import Condition, Listing, Money, SearchQuery, SellerKind
from bonneaffaire.providers import (
    Capabilities,
    ProviderBlocked,
    ProviderError,
    ProviderTimeout,
    UnexpectedShape,
)

BLOCKED_STATUSES = frozenset({403, 429, 503})
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
        return Capabilities(native_urls=bool(self.site.native_url_hosts))

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

    async def _fetch(self, url: str) -> str:
        client = self._client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9"},
            follow_redirects=True,
        )
        try:
            response = await client.get(url, timeout=self.site.timeout_seconds)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(self.name, f"no answer from {url}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, f"request to {url} failed: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        if response.status_code in BLOCKED_STATUSES:
            raise ProviderBlocked(self.name, f"HTTP {response.status_code} from {url}")
        if response.status_code != 200:
            raise ProviderError(self.name, f"HTTP {response.status_code} from {url}")
        return response.text

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
