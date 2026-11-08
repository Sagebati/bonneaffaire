# bonneaffaire

A private tool that searches second-hand and retail marketplaces in one place, for a human and for AI agents.

## Searching

**Provider**:
A marketplace bonneaffaire can search, such as Vinted, Leboncoin or eBay.
_Avoid_: Source, site, connector, marketplace (when meaning the integration)

**Listing**:
One offer on a Provider: a specific item, sold by one seller, in one Condition, at one Price. On second-hand Providers it is one physical item; on retailers one product page can carry several Listings.
_Avoid_: Ad, annonce, item, result, product

**Search**:
Running one request against one or more Providers right now and getting back Listings.
_Avoid_: Lookup, scrape

**Filter**:
A constraint on a Search from the shared vocabulary (keywords, price range, Condition, location, sort) that every Provider understands the same way.
_Avoid_: Criteria, parameter

**Native URL**:
A search page address copied from a Provider's own website, handed to that Provider as the whole Search request.
_Avoid_: Search link, raw query

**Provider outcome**:
What happened when one Provider was asked during a Search: ok, blocked, timed out, or failed.
_Avoid_: Provider error, provider status

## Describing a Listing

**Condition**:
The state of the item, from a fixed set: New, Refurbished, LikeNew, Used, ForParts, Unknown. Refurbished means professionally restored and resold, usually with a warranty. The Provider's own wording is kept alongside it.
_Avoid_: State, état, quality, grade

**Seller kind**:
Whether the seller of a Listing is a Private person or a Professional, or Unknown when the Provider does not say.
_Avoid_: Seller type, pro/particulier

**Price**:
What the seller asks for the item itself, without shipping or fees.
_Avoid_: Cost, amount

**Shipping**:
What the buyer pays to have the item delivered, when the Provider states it.
_Avoid_: Delivery fee, postage

**Buyer fee**:
A charge the Provider adds on top of the Price, such as Vinted's buyer protection.
_Avoid_: Protection fee, service fee

**Total cost**:
Price plus Shipping plus Buyer fee; only known when all three are.
_Avoid_: Final price, all-in price
