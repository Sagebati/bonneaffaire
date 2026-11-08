# Vinted fixtures: where they come from

All three were recorded from www.vinted.fr on 2026-11-08 through `vinted_scraper` 5.2.0
(anonymous session) and then trimmed. None is synthetic.

- `search-disque-dur.json`: `svc-catalogue/items?search_text=disque dur&order=price_low_to_high&price_from=10&per_page=20`.
  All 20 items kept. The duplicate `photos` array was removed from each item (`photo` stays).
- `search-disque-dur-neuf.json`: the same search with `attribute_ids[status]=6,1&price_to=200&order=newest_first&per_page=96`.
  Kept the first 6 items plus the first 2 from Vinted Pro sellers (`user.business: true`), with `photos` removed.
- `item-10718798068.html`: the item page, trimmed to its `<head>`, the JSON-LD Product
  script, and the 4 `self.__next_f.push` flight scripts that carry the plugins (attributes,
  seller, gallery) and `pricingServices` (buyer protection and shipping). The other 97
  scripts were dropped.

The landing page that starts the anonymous session is not a fixture. The tests build a
minimal one with a session cookie and an `X-Anon-Id` header, which is all the library reads.
