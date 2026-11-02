"""Travel Intelligence Tool (REST Countries API v5).

Usage:
    python travel_tool.py Japan
    python travel_tool.py "South Africa" --save
    python travel_tool.py Japan --raw        # print the raw API record (debugging)

Setup:
    1. Get a free API key at https://restcountries.com/sign-up
    2. Put it in a .env file:  COUNTRY_API_KEY=your_key   (or set the env variable)
    3. Settings (endpoint, timeout, fields) live in config.json.
       Set COUNTRY_API_BASE_URL to override the endpoint without editing files.
"""
import argparse
import json
import os
import re
import sys

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")
NA = "N/A"


class TravelToolError(Exception):
    """Any failure we can explain to the user in one clear sentence."""


# ---------- Step 3: configuration ----------
def _load_dotenv(path=ENV_PATH):
    """Tiny .env reader (KEY=VALUE per line) so no extra package is needed."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path=CONFIG_PATH):
    _load_dotenv()
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        raise TravelToolError(f"Config file not found: {path}")
    except json.JSONDecodeError as e:
        raise TravelToolError(f"Config file is not valid JSON: {e}")

    for key in ("base_url", "api_key_env", "timeout_seconds", "response_fields"):
        if key not in cfg:
            raise TravelToolError(f"Config is missing required key '{key}'.")

    env_url = os.environ.get("COUNTRY_API_BASE_URL")
    if env_url:
        cfg["base_url"] = env_url
    cfg["base_url"] = cfg["base_url"].rstrip("/")
    return cfg


def get_api_key(cfg):
    key = os.environ.get(cfg["api_key_env"], "").strip()
    if not key:
        raise TravelToolError(
            f"No API key found. Get a free key at https://restcountries.com/sign-up, then add "
            f"{cfg['api_key_env']}=your_key to a .env file next to travel_tool.py."
        )
    return key


# ---------- Step 1 & 2: fetching with error handling ----------
def _error_message(response):
    """Best-effort message from an error response body."""
    try:
        body = response.json()
        errors = body.get("errors") if isinstance(body, dict) else None
        if errors and isinstance(errors[0], dict) and errors[0].get("message"):
            return str(errors[0]["message"])
    except ValueError:
        pass
    return None


def _get(url, params, cfg, api_key):
    """GET a URL. Returns parsed JSON, or None for a 404 (not found)."""
    timeout = cfg["timeout_seconds"]
    try:
        response = requests.get(url, params=params, timeout=timeout,
                                headers={"Authorization": f"Bearer {api_key}"})
    except requests.exceptions.Timeout:
        raise TravelToolError(f"The API did not respond within {timeout} seconds. Try again shortly.")
    except requests.exceptions.ConnectionError:
        raise TravelToolError("Could not connect to the API. Check your internet connection.")
    except requests.exceptions.RequestException as e:
        raise TravelToolError(f"Network error: {e}")

    status = response.status_code
    if status == 404:
        return None
    detail = _error_message(response)
    if status == 401:
        raise TravelToolError("The API rejected your key (401). Check that COUNTRY_API_KEY is correct and active.")
    if status == 403:
        raise TravelToolError(f"Access forbidden (403). {detail or 'Your account may be frozen or over its monthly limit.'}")
    if status == 410:
        raise TravelToolError("This API version is no longer active (410). Update base_url in config.json.")
    if status == 429:
        raise TravelToolError("Too many requests (limit is about 20 per 10 seconds). Wait a moment and try again.")
    if status >= 500:
        raise TravelToolError(f"The API is having problems (HTTP {status}). Try again later.")
    if status >= 400:
        raise TravelToolError(f"The API rejected the request (HTTP {status}). {detail or ''}".strip())

    try:
        return response.json()
    except ValueError:
        raise TravelToolError("The API returned a response that is not valid JSON.")


def _snippet(payload, limit=200):
    return json.dumps(payload, default=str)[:limit]


def _objects(payload):
    """Pull the list of country records out of a v5 response envelope."""
    if payload is None:
        return []
    if isinstance(payload, dict) and payload.get("errors"):
        first = payload["errors"][0]
        msg = first.get("message") if isinstance(first, dict) else first
        raise TravelToolError(f"The API reported an error: {msg}")
    data = payload.get("data") if isinstance(payload, dict) else None
    objects = data.get("objects") if isinstance(data, dict) else None
    if not isinstance(objects, list) or not all(isinstance(o, dict) for o in objects):
        raise TravelToolError(f"The API returned data in an unexpected format: {_snippet(payload)}")
    return objects


def _validate_name(name):
    name = (name or "").strip()
    if not name:
        raise TravelToolError("Please enter a country name.")
    if not re.fullmatch(r"[^\W\d_]+(?:[ '.\-][^\W\d_]+)*\.?", name):
        raise TravelToolError(f"'{name}' doesn't look like a country name (use letters only).")
    return name


def _pick_best(results, query):
    """Prefer an exact name match; otherwise the first (most relevant) result."""
    q = query.lower()
    for item in results:
        names = item.get("names") if isinstance(item.get("names"), dict) else {}
        if q in (str(names.get("common", "")).lower(), str(names.get("official", "")).lower()):
            return item
    return results[0]


def fetch_country(name, cfg, api_key):
    """Return the raw API record for a country name."""
    name = _validate_name(name)
    base = cfg["base_url"]
    params = {"response_fields": cfg["response_fields"]}

    # 1) Exact (case-insensitive) match on the common name.
    results = _objects(_get(f"{base}/names.common/{requests.utils.quote(name)}", params, cfg, api_key))
    # 2) Fall back to a substring search across all name fields.
    if not results:
        results = _objects(_get(f"{base}/name", {**params, "q": name}, cfg, api_key))
    if not results:
        raise TravelToolError(f"No country found matching '{name}'. Check the spelling and try again.")
    return _pick_best(results, name)


def resolve_neighbours(alpha3, border_codes, cfg, api_key):
    """Neighbour names via the reverse-lookup endpoint; falls back to the raw codes."""
    if not border_codes:
        return []
    fallback = sorted(c for c in border_codes if isinstance(c, str))
    if not alpha3:
        return fallback
    try:
        payload = _get(f"{cfg['base_url']}/borders/{alpha3}",
                       {"response_fields": "names.common", "limit": 100}, cfg, api_key)
        names = [o["names"]["common"] for o in _objects(payload)
                 if isinstance(o.get("names"), dict) and o["names"].get("common")]
        return sorted(names) if names else fallback
    except TravelToolError:
        return fallback  # degrade gracefully: codes are better than nothing


# ---------- Step 1: parsing ----------
def _text(value, keys=("name", "english_name", "english", "common")):
    """Best-effort readable label from a string or a dict of unknown shape."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        for k in keys:
            found = _text(value.get(k), keys)
            if found:
                return found
        for v in value.values():
            if isinstance(v, str) and v:
                return v
    return None


def _items(collection):
    """Yield (key, value) pairs from either a dict or a list."""
    if isinstance(collection, dict):
        return list(collection.items())
    if isinstance(collection, list):
        return list(enumerate(collection))
    return []


def _parse_capitals(raw):
    capitals = raw.get("capitals")
    entries = []
    for _, c in _items(capitals):
        name = _text(c)
        if not name:
            continue
        attrs = c.get("attributes") if isinstance(c, dict) and isinstance(c.get("attributes"), dict) else {}
        entries.append((0 if attrs.get("primary") else 1, name))
    entries.sort(key=lambda e: e[0])
    return ", ".join(n for _, n in entries) or NA


def _parse_currencies(raw):
    out = []
    for key, d in _items(raw.get("currencies")):
        if isinstance(d, dict):
            label = _text(d) or NA
            code = d.get("code") or (key if isinstance(key, str) and len(key) == 3 else None)
            symbol = d.get("symbol")
            text = label + (f" ({symbol})" if symbol else "") + (f" [{code}]" if code else "")
        elif isinstance(d, str):
            text = d
        else:
            continue
        out.append(text)
    return out


def _parse_languages(raw):
    names = [_text(v) for _, v in _items(raw.get("languages"))]
    return sorted(n for n in names if n)


def parse_country(raw, neighbours):
    """Build a clean dictionary. Every field tolerates being missing."""
    names = raw.get("names") if isinstance(raw.get("names"), dict) else {}
    population = raw.get("population")
    return {
        "country": names.get("common") or NA,
        "official_name": names.get("official") or NA,
        "capital": _parse_capitals(raw),
        "currency": _parse_currencies(raw) or [NA],
        "population": int(population) if isinstance(population, (int, float))
                      and not isinstance(population, bool) else None,
        "languages": _parse_languages(raw) or [NA],
        "region": raw.get("region") or NA,
        "subregion": raw.get("subregion") or NA,
        "neighbours": neighbours or [],
    }


def get_travel_snapshot(name, cfg=None, raw_out=None):
    cfg = cfg or load_config()
    api_key = get_api_key(cfg)
    raw = fetch_country(name, cfg, api_key)
    if raw_out is not None:
        raw_out.update(raw)
    codes = raw.get("codes") if isinstance(raw.get("codes"), dict) else {}
    borders = raw.get("borders") if isinstance(raw.get("borders"), list) else []
    neighbours = resolve_neighbours(codes.get("alpha_3"), borders, cfg, api_key)
    return parse_country(raw, neighbours)


# ---------- Output ----------
def format_snapshot(info):
    pop = f"{info['population']:,}" if info["population"] is not None else NA
    neighbours = ", ".join(info["neighbours"]) if info["neighbours"] else "None (island or no land borders)"
    return "\n".join([
        f"TRAVEL SNAPSHOT: {info['country']}",
        "=" * 50,
        f"Official name : {info['official_name']}",
        f"Capital       : {info['capital']}",
        f"Currency      : {'; '.join(info['currency'])}",
        f"Population    : {pop}",
        f"Languages     : {', '.join(info['languages'])}",
        f"Region        : {info['region']} ({info['subregion']})",
        f"Neighbours    : {neighbours}",
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Get a travel snapshot for a country.")
    parser.add_argument("country", nargs="+", help="Country name, e.g. Japan or 'South Africa'")
    parser.add_argument("--save", action="store_true", help="Also save the result to sample_outputs/")
    parser.add_argument("--raw", action="store_true", help="Print the raw API record (for debugging)")
    args = parser.parse_args(argv)
    name = " ".join(args.country)

    raw = {}
    try:
        info = get_travel_snapshot(name, raw_out=raw)
    except TravelToolError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # last-resort safety net
        print(f"Unexpected error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if args.raw:
        print(json.dumps(raw, indent=2, ensure_ascii=False))
        print()
    text = format_snapshot(info)
    print(text)
    if args.save:
        os.makedirs("sample_outputs", exist_ok=True)
        path = os.path.join("sample_outputs", f"{info['country'].lower().replace(' ', '_')}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"\nSaved to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())