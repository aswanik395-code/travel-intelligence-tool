# Obstacle Log

> Edit this with your own experience, especially anything you hit when running against the live API.

| # | Obstacle | Solution |
|---|----------|----------|
| 1 | **The v3.1 endpoint was shut down.** Every request returned HTTP 200 with `{"success": false, "errors": [...deprecated...]}` and no data, so my code reported "unexpected format" for every country, even invalid ones. | Printed the raw response to find the cause, read the migration docs, and moved to the v5 API (`api.restcountries.com/countries/v5`). The response shape changed (`data.objects`, `names.common`, `capitals` as objects), so I rewrote the parser. |
| 2 | A shutdown returned HTTP 200, so checking the status code was not enough to detect failure. | `_objects()` also inspects the body: if it has an `errors` array, the API's own message is shown to the user. |
| 3 | v5 needs an API key, and a key must never be committed to GitHub. | Key is read from a `COUNTRY_API_KEY` environment variable or a local `.env` file, which is listed in `.gitignore`. `.env.example` shows the format. A missing key gives a clear setup message. |
| 4 | Neighbours come back as 3-letter codes (e.g. `BEL`), not names. | `resolve_neighbours()` uses the `/borders/{code}` reverse-lookup endpoint to get names in one call. If it fails, the codes are shown instead of crashing. |
| 5 | Name searches can match several countries (e.g. "Niger" and "Nigeria"). | Exact match on `names.common` first, then a substring search across name fields; the exact-name result is preferred. |
| 6 | Fields are nested and shaped differently (`capitals` is a list of objects, `currencies` and `languages` vary). | `parse_country()` uses small helper functions that tolerate dicts, lists or strings, and every field has a safe default (`N/A`). |
| 7 | The API limits requests to about 20 per 10 seconds, and the sample runner makes several calls. | Added a 1-second pause between countries in `run_samples.py`, and a clear message for HTTP 429. |
| 8 | Failure cases (timeouts, 401, 403, 429, 5xx) cannot be triggered on demand against a live API. | Wrote 15 offline unit tests with a mocked `requests.get`. |
| 9 | Endpoint was hardcoded in the logic. | Moved it to `config.json`, with a `COUNTRY_API_BASE_URL` override. |