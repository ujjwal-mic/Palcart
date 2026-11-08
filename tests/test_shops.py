"""Small tests that need no internet and no API keys. Run:  python -m pytest tests"""
import os

from backend.channel3_client import _clean_product
from backend.guest_checkout_sites import checkout_tier


def product(domain, price=9, **extra):
    offer = {"domain": domain, "url": f"https://{domain}/p", "price": {"price": price, "currency": "USD"}}
    return {"id": domain, "title": "LEGO set", "offers": [offer], **extra}


def test_trusted_shop_is_kept():
    assert _clean_product(product("officedepot.com"))["guest_checkout"] is True


def test_account_only_shop_is_skipped():
    assert checkout_tier("amazon.com") == 2
    assert _clean_product(product("amazon.com")) is None


def test_unknown_shop_is_skipped_unless_allowed(monkeypatch):
    monkeypatch.delenv("ALLOW_UNKNOWN_SHOPS", raising=False)
    assert _clean_product(product("random-deals.shop")) is None
    monkeypatch.setenv("ALLOW_UNKNOWN_SHOPS", "true")
    assert _clean_product(product("random-deals.shop")) is not None


def test_extra_shops_from_env(monkeypatch):
    monkeypatch.setenv("EXTRA_GUEST_CHECKOUT_SITES", "myshop.com")
    assert checkout_tier("www.myshop.com") == 0


def test_cheapest_trusted_offer_wins():
    raw = product("target.com", 20)
    raw["offers"].append({"domain": "lego.com", "url": "https://lego.com/p", "price": {"price": 15, "currency": "USD"}})
    assert _clean_product(raw)["price"] == 15


def test_picture_is_read():
    assert _clean_product(product("lego.com", image_urls=["https://i.example/a.jpg"]))["image_url"] == "https://i.example/a.jpg"
