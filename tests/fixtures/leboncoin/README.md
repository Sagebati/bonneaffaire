# Leboncoin fixtures

Recorded from the live API on 2026-11-08 through the `lbc` client, anonymous, from a
French residential IP:

- `search-disque-dur-8-to.json`: `POST https://api.leboncoin.fr/finder/search`, keywords
  "disque dur 8 To", category Électronique (14), limit 35.
- `ad-3299313803.json`: `GET https://api.leboncoin.fr/api/adfinder/v1/classified/3299313803`.
- `geocode-lyon.json`: `GET https://data.geopf.fr/geocodage/search?q=Lyon&index=address&type=municipality&limit=1`
  (the French address API, used to turn a place into coordinates for the location filter).

Synthetic (not recorded):

- `datadome-403.json`: the body of a DataDome block, written by hand after DataDome's
  documented JSON challenge shape (`{"url": "https://geo.captcha-delivery.com/captcha/?..."}`),
  served with HTTP 403. We did not provoke a real block to record one. What matters to
  the Provider is the 403 status, which `lbc` turns into `DatadomeError`.

Some tests edit a copy of a recorded response in memory (a professional seller, a missing
condition) for cases the recording does not contain; each such test says so.

Refresh the recorded files when Leboncoin changes its API; the live canary
(`tests/canary/test_leboncoin_live.py`) is the early warning.
