"""
kernel_cdp.py  -  THE CLOUD BROWSER (KERNEL + Playwright)
=========================================================

WHAT THIS FILE DOES
    After the human has paid us on PayPal, this file buys the item from the
    real merchant's website, using a robot browser.

WHAT IS KERNEL?
    KERNEL rents us a Chrome browser that runs in the cloud. That's more
    reliable than a browser on your laptop (no sleeping laptop, no crashes).

WHAT IS CDP?
    CDP = Chrome DevTools Protocol. It is a way to remote-control Chrome over
    the internet. KERNEL gives us a CDP address (a "ws://..." link).

WHAT IS PLAYWRIGHT?
    A library that clicks and types in a browser for us. We point it at the
    KERNEL CDP address, and it controls the cloud browser.

THE STEPS
    1. Ask KERNEL for a new cloud browser  -> we get a CDP address
    2. Connect Playwright to that address
    3. Open the product page, add to cart, go to checkout, fill the forms
    4. (Only if DRY RUN is off) press the final "Pay" button
    5. Always close the cloud browser (it costs money while open!)

SAFETY
    * The card comes from .env. The AI never sees it.
    * KERNEL_DRY_RUN=true (the default) fills the forms but does NOT press
      the final pay button. Use this while testing!
"""

import asyncio
import os
from pathlib import Path

from kernel import Kernel  # the official KERNEL Python SDK
from playwright.async_api import async_playwright


class CheckoutError(Exception):
    """Raised when the robot could not finish the checkout."""


# --------------------------------------------------------------------------
# Every shop's website is different! These lists hold "selectors" (ways to
# find a button or field on the page). We try each one in order until one
# works. For your demo merchant you can add the exact selector at the top.
# --------------------------------------------------------------------------
ADD_TO_CART_BUTTONS = [
    "button:has-text('Add to cart')",
    "button:has-text('Add to bag')",
    "button:has-text('Buy now')",
    "[name='add']",
    "#add-to-cart",
    "button:has-text('Add')",
    "[data-testid*='add-to-cart' i]",
    "[data-test*='add-to-cart' i]",
    "[id*='add-to-cart' i]",
    "[class*='add-to-cart' i]",
    "[aria-label*='add to cart' i]",
]
CHECKOUT_BUTTONS = [
    "button:has-text('Checkout')",
    "a:has-text('Checkout')",
    "button:has-text('Check out')",
    "[name='checkout']",
]
FORM_FIELDS = {
    # field name -> selectors to try
    "email": ["input[type='email']", "input[name*='email' i]"],
    "name": ["input[name*='name' i]"],
    "address": ["input[name*='address' i]", "input[autocomplete='address-line1']"],
    "city": ["input[name*='city' i]"],
    "zip": ["input[name*='zip' i]", "input[name*='postal' i]"],
    "card_number": ["input[autocomplete='cc-number']", "input[name*='cardnumber' i]"],
    "card_exp": ["input[autocomplete='cc-exp']", "input[name*='exp' i]"],
    "card_cvv": ["input[autocomplete='cc-csc']", "input[name*='cvc' i]", "input[name*='cvv' i]"],
}
PAY_BUTTONS = [
    "button:has-text('Pay now')",
    "button:has-text('Place order')",
    "button:has-text('Complete order')",
]
# Words that appear on a "your order worked" page.
SUCCESS_WORDS = ["thank you", "order confirmed", "order placed", "confirmation"]


async def click_first_that_works(page, selectors: list[str], rounds: int = 1) -> bool:
    """
    Try each selector. Click the first visible one. Return True if we clicked.

    rounds = how many times to look again. Modern shops draw their buttons a
    moment AFTER the page loads, so for important buttons we look several
    times, waiting 1.5 seconds between looks.
    """
    for attempt in range(rounds):
        for selector in selectors:
            try:
                button = page.locator(selector).first
                if await button.is_visible():
                    await button.click()
                    return True
            except Exception:
                continue  # not found, try the next one
        if attempt < rounds - 1:
            await page.wait_for_timeout(1500)  # wait, then look again
    return False


async def describe_page(page, order_id: str, label: str) -> str:
    """
    When the robot gets stuck, describe what it can see. This text ends up in the
    dashboard's Notes column, plus a screenshot is saved in the "artifacts" folder.
    """
    shot = ""
    try:
        Path("artifacts").mkdir(exist_ok=True)
        path = f"artifacts/{order_id}-{label}.png"
        await page.screenshot(path=path)
        shot = f" Screenshot saved: {path}."
    except Exception:
        pass
    try:
        title = await page.title()
    except Exception:
        title = "?"
    try:
        # Collect the text of the first 15 visible buttons on the page.
        buttons = await page.eval_on_selector_all(
            "button, a[role='button'], input[type='submit']",
            """els => els.filter(e => e.offsetParent !== null)
                        .map(e => (e.innerText || e.value || e.getAttribute('aria-label') || '').trim())
                        .filter(t => t).slice(0, 15)""",
        )
    except Exception:
        buttons = []
    return f"Page: '{title}' at {page.url}. Buttons seen: {buttons}.{shot}"


async def fill_first_that_works(page, selectors: list[str], value: str) -> None:
    """
    Type a value into the first matching field.
    Payment fields are often inside "iframes" (little pages inside the page),
    so we check the main page AND every iframe.
    """
    for frame in page.frames:  # page.frames includes the main page too
        for selector in selectors:
            try:
                field = frame.locator(selector).first
                if await field.is_visible():
                    await field.fill(value)
                    return
            except Exception:
                continue


def video_enabled() -> bool:
    """ORDER_VIDEO in .env: true = record every order (default: off)."""
    return os.getenv("ORDER_VIDEO", "false").lower() == "true"


def replay_file(order_id: str) -> Path:
    """Where the recording of an order is saved on our server."""
    return Path("artifacts") / "replays" / f"{order_id}.mp4"


async def save_replay(kernel, session_id: str, replay_id: str, order_id: str) -> bool:
    """
    Stop the recording and save the video file. Never raises: a missing video
    must NEVER make an order fail. Returns True if the file was saved.
    """
    try:
        await asyncio.to_thread(kernel.browsers.replays.stop, replay_id, id_or_name=session_id)
    except Exception as error:
        print(f"[kernel] could not stop recording: {error}")
        return False

    # KERNEL needs a few seconds to finish the video file, so try a few times.
    for _ in range(8):
        try:
            response = await asyncio.to_thread(
                kernel.browsers.replays.download, replay_id, id_or_name=session_id
            )
            data = await asyncio.to_thread(response.read)
            if data:
                target = replay_file(order_id)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                print(f"[kernel] recording saved: {target}")
                return True
        except Exception:
            pass  # not ready yet
        await asyncio.sleep(2.5)
    print("[kernel] recording was not ready in time")
    return False


async def buy_from_merchant(product_url: str, order_id: str, report=None) -> str:
    """
    Do the whole merchant checkout in a KERNEL cloud browser.

    report : optional function. We call report(live_view_url=...) etc. so the
             dashboard can show the live video and the replay link.

    Returns a short text describing what happened.
    Raises CheckoutError if something went wrong.
    """
    if not os.getenv("KERNEL_API_KEY"):
        raise CheckoutError("KERNEL_API_KEY is missing in .env")

    # Dry run = practice mode. ON unless you explicitly set it to "false".
    dry_run = os.getenv("KERNEL_DRY_RUN", "true").lower() != "false"

    # Our delivery + card details, read from .env (never shown to the AI).
    details = {
        "email": os.getenv("SHIP_EMAIL", ""),
        "name": os.getenv("SHIP_NAME", ""),
        "address": os.getenv("SHIP_ADDRESS", ""),
        "city": os.getenv("SHIP_CITY", ""),
        "zip": os.getenv("SHIP_ZIP", ""),
        "card_number": os.getenv("VIRTUAL_CARD_NUMBER", ""),
        "card_exp": os.getenv("VIRTUAL_CARD_EXP", ""),
        "card_cvv": os.getenv("VIRTUAL_CARD_CVV", ""),
    }

    # Headless = a browser with no visible window. KERNEL can only show a LIVE VIEW
    # (so you can watch the robot) when it is NOT headless. Default: watchable.
    headless = os.getenv("KERNEL_HEADLESS", "false").lower() == "true"

    # ---- STEP 1: ask KERNEL for a cloud browser ----
    kernel = Kernel()  # reads KERNEL_API_KEY from the environment
    try:
        # The KERNEL SDK waits for the network, so we run it in a side thread.
        session = await asyncio.to_thread(
            kernel.browsers.create, headless=headless, stealth=True, timeout_seconds=300
        )
    except Exception as error:
        raise CheckoutError(f"Could not start KERNEL browser: {error}")

    # session.cdp_ws_url is the remote-control address. The "live view" link
    # lets you WATCH the browser in your own web browser. Great for demos!
    live_view = getattr(session, "browser_live_view_url", None)
    print(f"[kernel] WATCH LIVE: {live_view or 'not available (check KERNEL_HEADLESS=false in .env)'}")

    # ORDER_VIDEO=true: show the live video in the dashboard and record it for later.
    replay_id = None
    if video_enabled():
        if report and live_view:
            report(live_view_url=live_view)
        try:
            replay = await asyncio.to_thread(kernel.browsers.replays.start, session.session_id)
            replay_id = replay.replay_id
        except Exception as error:
            print(f"[kernel] recording could not start (live view still works): {error}")

    try:
        async with async_playwright() as playwright:
            # ---- STEP 2: connect Playwright to the cloud browser ----
            browser = await playwright.chromium.connect_over_cdp(session.cdp_ws_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
            page.set_default_timeout(20_000)  # wait at most 20 seconds for things

            # ---- STEP 3: walk through the shop ----
            await page.goto(product_url, wait_until="domcontentloaded")
            # Give the shop time to finish loading (its buttons appear a moment later).
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass  # some shops never go fully quiet; that's okay
            await click_first_that_works(page, ["button:has-text('Accept')", "button:has-text('Got it')", "button[aria-label='Close']"])

            # Look for the button for up to ~12 seconds.
            if not await click_first_that_works(page, ADD_TO_CART_BUTTONS, rounds=8):
                raise CheckoutError(
                    "Could not find an 'Add to cart' button. "
                    + await describe_page(page, order_id, "no-add-to-cart")
                )
            await page.wait_for_timeout(1500)

            if not await click_first_that_works(page, CHECKOUT_BUTTONS):
                # No button? Many shops have a /checkout page we can open directly.
                site = "/".join(page.url.split("/")[:3])
                await page.goto(f"{site}/checkout", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)

            # Fill in every form field we have a value for.
            for field_name, value in details.items():
                if value:
                    await fill_first_that_works(page, FORM_FIELDS[field_name], value)

            # ---- STEP 4: the final button ----
            if dry_run:
                # Take a picture so we can see how far the robot got.
                Path("artifacts").mkdir(exist_ok=True)
                await page.screenshot(path=f"artifacts/{order_id}-dry-run.png")
                return "DRY RUN: checkout filled in, pay button NOT pressed"

            if not await click_first_that_works(page, PAY_BUTTONS):
                raise CheckoutError(
                    "Could not find the final pay button. "
                    + await describe_page(page, order_id, "no-pay-button")
                )
            await page.wait_for_timeout(5000)

            # Did it work? Look for "thank you" style words on the page.
            page_text = (await page.inner_text("body")).lower()
            if not any(word in page_text for word in SUCCESS_WORDS):
                raise CheckoutError("Pressed pay, but no confirmation page appeared")
            return "Merchant checkout completed"

    except CheckoutError:
        raise  # already a nice message
    except Exception as error:
        raise CheckoutError(str(error))
    finally:
        # ---- STEP 5: save the recording, then ALWAYS close the cloud browser ----
        if report:
            report(live_view_url=None)  # the live view is over
        if replay_id and await save_replay(kernel, session.session_id, replay_id, order_id):
            if report:
                report(replay_url=f"/api/orders/{order_id}/replay")
        try:
            await asyncio.to_thread(kernel.browsers.delete_by_id, session.session_id)
        except Exception as error:
            print(f"[kernel] could not close session: {error}")
