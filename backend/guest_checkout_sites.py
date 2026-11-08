"""
guest_checkout_sites.py  -  WHICH SHOPS LET YOU BUY WITHOUT AN ACCOUNT
======================================================================

WHY THIS EXISTS
    Our shopping robot can't log in or create accounts. It only knows how to
    check out as a GUEST. So when we search for products, we want shops that
    allow guest checkout to come FIRST, and shops that force an account to be
    left out.

HOW IT IS USED
    channel3_client.py asks checkout_tier(shop) for every offer:
        0 = known to allow guest checkout   -> shown first
        1 = unknown                         -> SKIPPED (unless ALLOW_UNKNOWN_SHOPS=true in .env)
        2 = needs an account                -> never shown

IMPORTANT: THIS LIST IS A BEST GUESS
    Shops change their rules, and some shops block robots even when guest
    checkout is allowed. Test a shop yourself (add to cart in a private
    browser window and see if checkout asks you to log in) and edit the lists
    below. You can also add shops without touching code, with this line in .env:
        EXTRA_GUEST_CHECKOUT_SITES=myshop.com,anothershop.com
"""

import os

# Shops that usually allow guest checkout.
GUEST_FRIENDLY = {
    "target.com",
    "bestbuy.com",
    "homedepot.com",
    "lowes.com",
    "newegg.com",
    "bhphotovideo.com",
    "staples.com",
    "officedepot.com",
    "wayfair.com",
    "etsy.com",
    "ebay.com",
    "nike.com",
    "macys.com",
    "kohls.com",
    "lego.com",
}

# Shops that usually REQUIRE an account or a membership. We skip these.
NEEDS_ACCOUNT = {
    "amazon.com",
    "costco.com",
    "samsclub.com",
}


def _clean(domain: str) -> str:
    """Make 'https://www.Target.com/path' look like 'target.com'."""
    domain = (domain or "").strip().lower()
    domain = domain.split("://")[-1].split("/")[0]
    return domain[4:] if domain.startswith("www.") else domain


def _in_group(domain: str, group) -> bool:
    """True if the domain is in the group, or is a sub-domain of one (shop.target.com)."""
    return any(domain == d or domain.endswith("." + d) for d in group)


def _extra_sites() -> set:
    """Extra guest-friendly shops the user listed in .env."""
    raw = os.getenv("EXTRA_GUEST_CHECKOUT_SITES", "")
    return {_clean(part) for part in raw.split(",") if part.strip()}


def checkout_tier(domain: str) -> int:
    """0 = guest checkout (best), 1 = unknown, 2 = needs an account (skip)."""
    domain = _clean(domain)
    if _in_group(domain, NEEDS_ACCOUNT):
        return 2
    if _in_group(domain, GUEST_FRIENDLY | _extra_sites()):
        return 0
    return 1
