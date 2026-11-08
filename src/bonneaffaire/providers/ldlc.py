"""LDLC, defined as configuration of the generic retail Provider."""

import httpx

from bonneaffaire.models import Condition, SellerKind
from bonneaffaire.providers.retail import Pick, RetailProvider, RetailSite, SearchPage

LDLC = RetailSite(
    name="ldlc",
    country="FR",
    base_url="https://www.ldlc.com/",
    search_url="https://www.ldlc.com/recherche/{keywords}/",
    currency="EUR",
    condition=Condition.NEW,
    condition_label="Neuf",
    seller_kind=SellerKind.PROFESSIONAL,
    product_url="https://www.ldlc.com/fiche/{provider_id}.html",
    search_page=SearchPage(
        card="li.pdt-item",
        title=Pick(".pdt-desc h3 a"),
        link=Pick(".pdt-desc h3 a", "href"),
        price=Pick(".basket .price"),
        thumbnail=Pick(".pic img", "src"),
        provider_id_pattern=r"/fiche/([A-Z0-9]+)\.html",
        no_results_text="Aucun produit",
        attributes={
            "description": Pick(".pdt-desc .desc"),
            "offer_id": Pick(":self", "data-offer-id"),
        },
    ),
    native_url_hosts=frozenset({"www.ldlc.com", "ldlc.com"}),
    native_url_path_prefix="/recherche/",
)


def ldlc(client: httpx.AsyncClient | None = None) -> RetailProvider:
    return RetailProvider(LDLC, client=client)
