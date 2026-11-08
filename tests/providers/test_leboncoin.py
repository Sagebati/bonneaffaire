"""Leboncoin, fed recorded API responses through the `lbc` client (Seam 2)."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from lbc_replay import AD_URL, SEARCH_URL, Recorded, ReplaySession, fixture, replaying_client

from bonneaffaire.models import Condition, Location, Money, SearchQuery, SellerKind, Sort
from bonneaffaire.providers import ListingNotFound, ProviderBlocked, ProviderError, UnexpectedShape
from bonneaffaire.providers.leboncoin import leboncoin

SEARCH = fixture("search-disque-dur-8-to.json")
GEOCODE_LYON = fixture("geocode-lyon.json")


def geocoder_replay() -> httpx.AsyncClient:
    """The French address API answering the recorded lookup for Lyon, nothing for others."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("q") == "Lyon":
            return httpx.Response(200, text=GEOCODE_LYON)
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def provider_answering(answers: dict[str, Recorded]):
    session = ReplaySession(answers)
    provider = leboncoin(client_factory=lambda: replaying_client(session), http=geocoder_replay())
    return provider, session


async def test_keyword_search_returns_listings_from_the_search_response():
    provider, _ = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)

    assert len(listings) == 35
    first = listings[0]
    assert first.provider == "leboncoin"
    assert first.provider_id == "3299313803"
    assert first.title == "Disque dur 8 To Seagate IronWolf NAS ST8000VN004"
    assert first.url == "https://www.leboncoin.fr/ad/accessoires_informatique/3299313803"
    assert first.price == Money(cents=25000, currency="EUR")
    assert first.condition == Condition.NEW
    assert first.condition_label == "État neuf"
    assert first.seller_kind == SellerKind.PRIVATE
    assert first.location == "Villeurbanne 69100"


async def test_shipping_is_the_cheapest_offered_option_and_absent_for_hand_delivery():
    provider, _ = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)
    by_id = {listing.provider_id: listing for listing in listings}

    # mondial_relay 3.99, shop2shop 3.99, colissimo 9.59
    assert by_id["3299313803"].shipping == Money(cents=399, currency="EUR")
    # hand delivery only: no shipping_fees in the response
    assert by_id["3279270463"].shipping is None
    assert by_id["3279270463"].attributes["shipping_types"] == ["face_to_face"]


async def test_thumbnail_posting_time_and_raw_attributes_are_kept():
    provider, _ = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})

    first = (await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=1))[0]

    assert first.thumbnail == (
        "https://img.leboncoin.fr/api/v1/lbcpb1/images/86/30/b8/"
        "8630b811521396785cc215439f7a72968b7a9864.jpg?rule=ad-thumb"
    )
    assert first.posted_at == datetime(2026, 10, 31, 16, 4, 28, tzinfo=ZoneInfo("Europe/Paris"))
    assert first.attributes["category"] == "Accessoires informatique"
    assert first.attributes["brand"] == "Western Digital"
    assert first.attributes["condition_value"] == "etatneuf"
    assert first.attributes["zipcode"] == "69100"
    assert first.attributes["quoted_buyer_fee_cents"] == 199


async def test_the_stated_buyer_fee_counts_only_for_listings_that_offer_shipping():
    provider, _ = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)
    by_id = {listing.provider_id: listing for listing in listings}

    shipped = by_id["3299313803"]
    assert shipped.buyer_fee == Money(cents=199, currency="EUR")
    assert shipped.total_cost == Money(cents=25000 + 399 + 199, currency="EUR")
    # Hand delivery only: no Buyer fee is charged through Leboncoin, so it stays unknown.
    assert by_id["3279270463"].buyer_fee is None


async def test_conditions_map_from_leboncoin_labels_and_keep_the_raw_label():
    provider, _ = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)
    by_id = {
        listing.provider_id: (listing.condition, listing.condition_label) for listing in listings
    }

    assert by_id["3299313803"] == (Condition.NEW, "État neuf")
    assert by_id["3277266081"] == (Condition.LIKE_NEW, "Très bon état")
    assert by_id["3288536570"] == (Condition.USED, "Bon état")
    assert by_id["3296353624"] == (Condition.USED, "État satisfaisant")


def edited_search(edit) -> str:
    """The recorded search with its first ad edited, for cases the recording lacks."""
    body = json.loads(SEARCH)
    edit(body["ads"][0])
    return json.dumps(body)


async def test_a_professional_seller_and_a_listing_without_condition():
    def professional_without_condition(ad):
        ad["owner"]["type"] = "pro"
        ad["attributes"] = [a for a in ad["attributes"] if a["key"] != "condition"]

    provider, _ = provider_answering(
        {SEARCH_URL: Recorded(200, edited_search(professional_without_condition))}
    )

    first = (await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=1))[0]

    assert first.seller_kind == SellerKind.PROFESSIONAL
    assert first.condition == Condition.UNKNOWN
    assert first.condition_label is None


async def test_a_for_parts_listing_maps_to_for_parts():
    def damaged(ad):
        for attribute in ad["attributes"]:
            if attribute["key"] == "condition":
                attribute.update(value="pourpieces", value_label="Pour pièces")

    provider, _ = provider_answering({SEARCH_URL: Recorded(200, edited_search(damaged))})

    first = (await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=1))[0]

    assert (first.condition, first.condition_label) == (Condition.FOR_PARTS, "Pour pièces")


async def test_limit_is_asked_of_leboncoin_and_caps_the_listings():
    provider, session = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})

    listings = await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=5)

    assert len(listings) == 5
    [payload] = session.payloads()
    assert payload["limit"] == 5
    assert payload["filters"]["keywords"] == {"text": "disque dur 8 To"}


async def test_filters_location_price_sort_and_category_are_applied_natively():
    provider, session = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})
    query = SearchQuery(
        keywords="disque dur 8 To",
        price_min=Money(cents=9950, currency="EUR"),
        price_max=Money(cents=30000, currency="EUR"),
        location=Location(place="Lyon", radius_km=30),
        sort=Sort.PRICE,
        extras={"leboncoin": {"category": "ELECTRONIQUE_ACCESSOIRES_INFORMATIQUE"}},
    )

    await provider.search(query, limit=50)

    [payload] = session.payloads()
    filters = payload["filters"]
    # Whole euros, rounded outward so no Listing inside the range is lost.
    assert filters["ranges"]["price"] == {"min": 99, "max": 300}
    [place] = filters["location"]["locations"]
    assert place["locationType"] == "city"
    assert place["area"] == {"lat": 45.758, "lng": 4.835, "radius": 30_000}
    assert filters["category"] == {"id": "83"}
    assert (payload["sort_by"], payload["sort_order"]) == ("price", "asc")
    assert provider.capabilities.native_filters == {
        "price_min",
        "price_max",
        "location",
        "sort",
    }
    assert provider.capabilities.extras == {"category"}


async def test_category_extra_also_takes_a_numeric_id_and_one_price_bound():
    provider, session = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})
    query = SearchQuery(
        keywords="disque dur",
        price_max=Money(cents=15000, currency="EUR"),
        sort=Sort.RECENCY,
        extras={"leboncoin": {"category": "15"}},
    )

    await provider.search(query, limit=50)

    [payload] = session.payloads()
    assert payload["filters"]["category"] == {"id": "15"}
    assert payload["filters"]["ranges"]["price"]["max"] == 150
    assert payload["filters"]["ranges"]["price"].get("min", 0) == 0
    assert (payload["sort_by"], payload["sort_order"]) == ("time", "desc")


async def test_an_unknown_category_or_place_fails_without_asking_leboncoin():
    provider, session = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})

    with pytest.raises(ProviderError, match="category"):
        await provider.search(
            SearchQuery(keywords="x", extras={"leboncoin": {"category": "NOPE"}}), limit=5
        )
    with pytest.raises(ProviderError, match="Atlantis"):
        await provider.search(SearchQuery(keywords="x", location=Location(place="Atlantis")), 5)
    assert session.payloads() == []


NATIVE_URL = (
    "https://www.leboncoin.fr/recherche?category=15&text=disque+dur%208%20To"
    "&locations=Lyon__45.758_4.835_10000_30000&price=50-200&sort=price&order=asc"
)


def test_leboncoin_search_pages_are_native_urls_and_other_pages_are_not():
    provider, _ = provider_answering({})

    assert provider.capabilities.native_urls
    assert provider.recognises_native_url(NATIVE_URL)
    assert provider.recognises_native_url("https://leboncoin.fr/recherche?text=nas")
    assert not provider.recognises_native_url(
        "https://www.leboncoin.fr/ad/accessoires_informatique/3299313803"
    )
    assert not provider.recognises_native_url("https://www.ldlc.com/recherche/nas/")
    assert not provider.recognises_native_url("https://www.leboncoin.fr.evil.example/recherche")


async def test_a_native_url_runs_the_search_it_describes():
    provider, session = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})

    listings = await provider.search(SearchQuery(native_url=NATIVE_URL), limit=20)

    assert len(listings) == 20
    [payload] = session.payloads()
    filters = payload["filters"]
    assert filters["keywords"]["text"] == "disque dur 8 To"
    assert filters["category"] == {"id": "15"}
    assert filters["ranges"]["price"] == {"min": 50, "max": 200}
    [place] = filters["location"]["locations"]
    assert place["area"] == {"lat": 45.758, "lng": 4.835, "default_radius": 10000, "radius": 30000}
    assert (payload["sort_by"], payload["sort_order"]) == ("price", "asc")
    assert payload["limit"] == 20


async def test_an_unreadable_native_url_fails_without_asking_leboncoin():
    provider, session = provider_answering({SEARCH_URL: Recorded(200, SEARCH)})

    with pytest.raises(ProviderError, match="Native URL"):
        await provider.search(
            SearchQuery(native_url="https://www.leboncoin.fr/recherche?locations=x_1"), limit=5
        )
    assert session.payloads() == []


def test_provider_ids_come_from_leboncoin_listing_urls():
    provider, _ = provider_answering({})

    assert provider.capabilities.listing_details
    assert (
        provider.listing_id_from_url(
            "https://www.leboncoin.fr/ad/accessoires_informatique/3299313803"
        )
        == "3299313803"
    )
    assert (
        provider.listing_id_from_url("https://www.leboncoin.fr/informatique/2985022714.htm?ac=1")
        == "2985022714"
    )
    assert provider.listing_id_from_url(NATIVE_URL) is None
    assert provider.listing_id_from_url("https://www.ldlc.com/fiche/PB00281525.html") is None


async def test_listing_details_come_from_the_details_response():
    provider, _ = provider_answering(
        {AD_URL.format(3299313803): Recorded(200, fixture("ad-3299313803.json"))}
    )

    details = await provider.get_listing("3299313803")

    assert details.provider_id == "3299313803"
    assert details.title == "Disque dur 8 To Seagate IronWolf NAS ST8000VN004"
    assert details.price == Money(cents=25000, currency="EUR")
    assert (details.condition, details.condition_label) == (Condition.NEW, "État neuf")
    assert details.seller_kind == SellerKind.PRIVATE
    assert details.location == "Villeurbanne 69100"
    assert details.description is not None
    assert details.description.startswith("Je mets en vente ce disque dur interne Seagate")
    assert details.photos == [
        "https://img.leboncoin.fr/api/v1/lbcpb1/images/86/30/b8/"
        "8630b811521396785cc215439f7a72968b7a9864.jpg?rule=ad-large"
    ]
    assert details.seller is not None
    assert details.seller.name == "Seller 053"
    # The ad endpoint quotes no shipping prices, only the delivery methods offered.
    assert details.shipping is None
    assert details.attributes["shipping_types"] == [
        "mondial_relay",
        "shop2shop",
        "colissimo",
        "face_to_face",
    ]
    assert details.attributes["favorites"] == 11


async def test_a_listing_that_is_gone_is_not_found():
    provider, _ = provider_answering({})  # the replay answers 404 to anything unrecorded

    with pytest.raises(ListingNotFound):
        await provider.get_listing("1")


async def test_a_datadome_403_is_reported_as_blocked():
    provider, session = provider_answering(
        {SEARCH_URL: Recorded(403, fixture("datadome-403.json"))}
    )

    with pytest.raises(ProviderBlocked, match="DataDome"):
        await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)
    assert len(session.payloads()) == 1, "a block must not be retried straight away"


async def test_a_search_with_no_results_is_empty():
    no_results = json.dumps({"total": 0, "total_all": 0, "max_pages": 0})
    provider, _ = provider_answering({SEARCH_URL: Recorded(200, no_results)})

    assert await provider.search(SearchQuery(keywords="zzzz"), limit=50) == []


@pytest.mark.parametrize(
    "body",
    [
        "<html>maintenance</html>",
        json.dumps({"message": "something else"}),
        json.dumps({"total": 1, "ads": [{"list_id": 1, "subject": "no price"}]}),
    ],
)
async def test_a_response_of_another_shape_is_an_unexpected_shape(body):
    provider, _ = provider_answering({SEARCH_URL: Recorded(200, body)})

    with pytest.raises(UnexpectedShape):
        await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)


async def test_a_server_error_fails_the_search():
    provider, _ = provider_answering({SEARCH_URL: Recorded(500, "oops")})

    with pytest.raises(ProviderError, match="500"):
        await provider.search(SearchQuery(keywords="disque dur 8 To"), limit=50)
