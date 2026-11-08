"""
channel3_client.py  -  PRODUCT DISCOVERY (Channel3 API)
=======================================================

WHAT THIS FILE DOES
    Asks Channel3 "what products match this search?" and gets back clean
    structured data (title, price, merchant link).

WHY WE USE IT
    The other way to find products is "web scraping": downloading a shop's
    web page and guessing where the price is. That breaks all the time.
    Channel3 gives us the price and link as tidy JSON instead.

HOW CHANNEL3 ORGANISES ITS DATA
    One PRODUCT (like "LEGO City Fire Truck") can be sold by many shops.
    So each product has a list called "offers", one per shop:

        product = {
          "id": "...", "title": "...",
          "offers": [
             {"domain": "target.com", "url": "https://...",
              "price": {"price": 34.99, "currency": "USD"},
              "availability": "InStock"},
             ...
          ]
        }

    For each product we pick the BEST offer: a shop that allows guest checkout
    comes first, then the lowest price. Shops that force an account are skipped
    (see guest_checkout_sites.py). Each product becomes one simple dictionary:
        {"id", "title", "merchant", "price", "currency", "url", "guest_checkout"}

HOW THE LIST IS ORDERED
    Channel3 sends results best-match first. We KEEP that order, but move products
    sold by guest-checkout shops to the top. So the first result is the best
    match that our robot is most likely to be able to buy.

WHY THIS MATTERS FOR SAFETY
    The price and link come from Channel3, NOT from the AI. The AI can't
    make up a price, because our code looks the price up from this data.
"""

import os

import httpx  # a library for making web requests (async)

from backend.guest_checkout_sites import checkout_tier

# The Channel3 API address. Search is:  POST {CHANNEL3_URL}/search
CHANNEL3_URL = os.getenv("CHANNEL3_BASE_URL", "https://api.trychannel3.com/v1").rstrip("/")


def _read_price(price) -> tuple[float, str] | None:
    """
    Read a price from an offer. Channel3 sends something like
        {"price": 110, "currency": "USD"}      (some versions say "amount")
    We also accept a plain number. Returns (amount, currency) or None.
    """
    currency = "USD"
    if isinstance(price, dict):
        currency = price.get("currency") or "USD"
        price = price.get("price", price.get("amount"))
    try:
        return float(price), str(currency)
    except (TypeError, ValueError):
        return None  # missing or not a real number


def allow_unknown_shops() -> bool:
    """ALLOW_UNKNOWN_SHOPS=true lets the robot buy from shops that are not on our trusted list."""
    return os.getenv("ALLOW_UNKNOWN_SHOPS", "false").lower() == "true"


def _read_image(raw: dict) -> str | None:
    """Find the product picture. Channel3 may name it a few different ways."""
    candidates = [raw.get("image_url"), raw.get("image")]
    for key in ("image_urls", "images"):
        for item in raw.get(key) or []:
            candidates.append(item.get("url") if isinstance(item, dict) else item)
    for url in candidates:
        if isinstance(url, str) and url.startswith("http"):
            return url
    return None


def _clean_product(raw: dict) -> dict | None:
    """
    Turn ONE Channel3 product into our simple dictionary.
    Returns None if it has no usable offer (no price/link, sold out, or only
    sold by shops that force an account).
    """
    best = None  # (tier, price, currency, merchant, url)
    for offer in raw.get("offers") or []:
        # Skip items that are sold out. (If availability is missing, allow it.)
        if offer.get("availability") not in (None, "InStock"):
            continue
        parsed = _read_price(offer.get("price"))
        url = offer.get("url")
        if not parsed or not url:
            continue
        price, currency = parsed
        merchant = offer.get("domain") or offer.get("merchant") or "unknown"

        tier = checkout_tier(merchant)
        if tier == 2:
            continue  # this shop needs an account: our robot can't use it
        if tier == 1 and not allow_unknown_shops():
            continue  # unknown shop: could be a broken or fake site, so skip it

        # Better offer = lower tier first (guest-friendly), then lower price.
        if best is None or (tier, price) < (best[0], best[1]):
            best = (tier, price, currency, merchant, url)

    # A simpler shape: price + url directly on the product.
    if best is None and raw.get("url") and raw.get("price") is not None:
        parsed = _read_price(raw.get("price"))
        merchant = raw.get("merchant") or raw.get("domain") or "unknown"
        tier_raw = checkout_tier(merchant)
        if parsed and (tier_raw == 0 or (tier_raw == 1 and allow_unknown_shops())):
            best = (checkout_tier(merchant), parsed[0], parsed[1], merchant, raw["url"])

    if best is None:
        return None

    tier, price, currency, merchant, url = best
    return {
        "id": str(raw.get("id") or url),
        "title": str(raw.get("title") or raw.get("name") or "Untitled"),
        "merchant": str(merchant),
        "price": price,
        "currency": currency,
        "url": url,
        "guest_checkout": tier == 0,
        "image_url": _read_image(raw),
    }


async def _ask_channel3(client: httpx.AsyncClient, api_key: str, body: dict) -> httpx.Response:
    """Send one search request to Channel3."""
    return await client.post(f"{CHANNEL3_URL}/search", json=body, headers={"x-api-key": api_key})


async def search_products(query: str, max_price: float | None = None) -> list[dict]:
    """
    Search Channel3 and return a list of clean products, guest-checkout shops first.

    "async def" means this function can WAIT for the internet without
    freezing the whole server. We call it with "await".
    """
    # .strip() removes stray spaces/quotes that sneak in when pasting a key into .env
    api_key = os.getenv("CHANNEL3_API_KEY", "").strip().strip("\"'")
    if not api_key:
        raise RuntimeError("CHANNEL3_API_KEY is not set in your .env file")

    # We ask for extra results, because some will be thrown away (sold out,
    # shops that need an account) and we want guest-friendly shops to appear.
    body = {"query": query, "limit": 40}
    if max_price is not None:
        body["filters"] = {"price": {"max_price": max_price}}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await _ask_channel3(client, api_key, body)
            if response.status_code == 422:  # maybe "limit" is too big: try a smaller one
                body["limit"] = 10
                response = await _ask_channel3(client, api_key, body)

            if response.status_code in (401, 403):
                # Key problem. Show a SAFE hint (length + first 4 characters, never the full key).
                raise RuntimeError(
                    f"Channel3 rejected the API key (HTTP {response.status_code}). "
                    f"The key we sent has {len(api_key)} characters and starts with '{api_key[:4]}'. "
                    "Check CHANNEL3_API_KEY in .env: it must be your real key (not the placeholder), "
                    "with no quotes or spaces, and you must restart the server after editing .env."
                )
            if response.status_code >= 400:
                raise RuntimeError(f"Channel3 answered HTTP {response.status_code}: {response.text[:200]}")
            data = response.json()
    except Exception as error:
        # Print the REAL reason in the terminal where the server is running.
        print(f"[channel3] search failed: {error}")
        raise RuntimeError(f"Channel3 search failed: {error}")

    # The answer looks like {"products": [...], "next_page_token": ...}.
    raw_products = data if isinstance(data, list) else data.get("products", [])

    # Clean every product and throw away the unusable ones.
    products = [p for p in (_clean_product(raw) for raw in raw_products) if p]

    # Double-check the price limit ourselves. Never trust a filter blindly.
    if max_price is not None:
        products = [p for p in products if p["price"] <= max_price]

    # Guest-checkout shops first. Python's sort is "stable", so inside each group
    # the products stay in Channel3's best-match-first order.
    products.sort(key=lambda p: not p["guest_checkout"])

    guest = sum(1 for p in products if p["guest_checkout"])
    print(f"[channel3] '{query}': {len(raw_products)} from Channel3, {len(products)} usable, {guest} from guest-checkout shops")
    return products[:8]
