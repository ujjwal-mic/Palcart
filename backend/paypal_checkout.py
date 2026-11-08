"""
paypal_checkout.py  -  PAYMENTS through the official PayPal MCP server
======================================================================

WHAT IS MCP?
    MCP = Model Context Protocol. It is a standard way for an AI app to talk
    to "tool servers". PayPal publishes an official MCP server (npm package
    "@paypal/mcp", part of the PayPal Agent Toolkit). It offers ready-made
    tools such as:

        create_order  -> creates a PayPal Checkout Order (intent = CAPTURE)
        get_order     -> reads an order, so we know its status (APPROVED?)
        pay_order     -> captures the money of an approved order

WHAT THIS FILE DOES
    * Starts the PayPal MCP server as a small helper program (needs Node.js).
    * Lets the rest of our app call its tools:  await paypal.call("create_order", {...})
    * Lists the tools' schemas, so the AI agent can use them as native tools.
    * Checks webhook signatures (the MCP server has no tool for that, so this
      one small piece uses PayPal's REST API directly).

WHY THIS KEEPS PAYMENTS SAFE
    The AI never sees card data. A human approves the payment on PayPal's own page.

HOW A CALL WORKS
    Our Python app  --(MCP over stdin/stdout)-->  PayPal MCP server (Node)  --(HTTPS)-->  PayPal
    To keep things simple and reliable, we start the server fresh for each call.
    It takes about a second, which is fine for a demo.
"""

import asyncio
import json
import os
import shlex
import shutil
import time

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Which PayPal tools we switch on. We only enable the order tools, so even a
# confused AI could not, say, send invoices or issue refunds.
ENABLED_TOOLS = "orders.create,orders.capture,orders.get"


class PayPalError(Exception):
    """Our own error type for any PayPal problem."""


def _is_live() -> bool:
    return os.getenv("PAYPAL_MODE", "sandbox").lower() == "live"


def _api_base() -> str:
    return "https://api-m.paypal.com" if _is_live() else "https://api-m.sandbox.paypal.com"


# --------------------------------------------------------------------------
# ACCESS TOKEN
# The MCP server logs in to PayPal with a temporary "access token", not with
# your client id + secret directly. We make the token here (valid ~9 hours)
# and remember it, so we don't ask PayPal for a new one every time.
# --------------------------------------------------------------------------
_token_cache = {"value": None, "expires_at": 0.0}


async def get_access_token() -> str:
    # Shortcut: you can paste a ready-made token into .env while testing.
    manual = os.getenv("PAYPAL_ACCESS_TOKEN", "").strip()
    if manual:
        return manual

    # Reuse the saved token while it is still fresh.
    if _token_cache["value"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["value"]

    client_id = os.getenv("PAYPAL_CLIENT_ID", "")
    client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise PayPalError("Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET in .env")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{_api_base()}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),  # "basic auth"
            )
            response.raise_for_status()
            data = response.json()
    except Exception as error:
        raise PayPalError(f"Could not get a PayPal access token: {error}")

    _token_cache["value"] = data["access_token"]
    # Renew 5 minutes early to be safe.
    _token_cache["expires_at"] = time.time() + int(data.get("expires_in", 3600)) - 300
    return _token_cache["value"]


# --------------------------------------------------------------------------
# THE MCP CLIENT
# --------------------------------------------------------------------------
class PayPalMCP:
    """A tiny client for the official PayPal MCP server."""

    def __init__(self) -> None:
        self._schemas: dict | None = None  # remembered after the first lookup

    async def _server_params(self) -> StdioServerParameters:
        """Describe HOW to start the PayPal MCP server program."""
        token = await get_access_token()

        # Normal case: "npx -y @paypal/mcp --tools=..." (needs Node.js 18+).
        # PAYPAL_MCP_COMMAND lets you override it, e.g. for a global install.
        override = os.getenv("PAYPAL_MCP_COMMAND", "").strip()
        if override:
            command = shlex.split(override)
        else:
            npx = shutil.which("npx")
            if not npx:
                raise PayPalError("Node.js is required (the 'npx' command was not found)")
            command = [npx, "-y", "@paypal/mcp", f"--tools={ENABLED_TOOLS}"]

        return StdioServerParameters(
            command=command[0],
            args=command[1:],
            # The server reads these two settings from its environment.
            env={
                **os.environ,
                "PAYPAL_ACCESS_TOKEN": token,
                "PAYPAL_ENVIRONMENT": "PRODUCTION" if _is_live() else "SANDBOX",
            },
        )

    async def _run(self, work):
        """Start the server, connect, run `work(session)`, then shut it down."""
        params = await self._server_params()

        async def go():
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()  # the MCP "hello" handshake
                    return await work(session)

        try:
            return await asyncio.wait_for(go(), timeout=90)
        except PayPalError:
            raise
        except Exception as error:
            raise PayPalError(f"PayPal MCP server problem: {error}")

    # ----------------------------------------------------------------------
    async def tool_schemas(self) -> dict[str, dict]:
        """
        Ask the server "what tools do you have?"
        Returns {tool_name: {"description": ..., "schema": <JSON schema>}}.
        The AI agent uses this so it can call the REAL PayPal tools natively.
        """
        if self._schemas is not None:
            return self._schemas

        async def work(session):
            listing = await session.list_tools()
            found = {}
            for tool in listing.tools:
                # mcp v1 calls it inputSchema, v2 calls it input_schema.
                schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", {})
                found[tool.name] = {"description": tool.description or "", "schema": schema}
            return found

        self._schemas = await self._run(work)
        return self._schemas

    async def call(self, tool_name: str, arguments: dict) -> dict:
        """
        Call one PayPal tool and return its answer as a Python dictionary.
        Raises PayPalError if PayPal reports a problem.
        """

        async def work(session):
            return await session.call_tool(tool_name, arguments)

        result = await self._run(work)

        # The answer arrives as text. PayPal's tools put JSON inside that text.
        text = "".join(getattr(part, "text", "") for part in result.content)
        failed_flag = getattr(result, "is_error", None) or getattr(result, "isError", False)

        try:
            data = json.loads(text)
        except ValueError:
            if failed_flag:
                raise PayPalError(f"{tool_name} failed: {text[:300]}")
            raise PayPalError(f"{tool_name} returned something unexpected: {text[:300]}")

        # Several ways an error can be reported. Check them all.
        if failed_flag or (isinstance(data, dict) and (data.get("error") or data.get("ok") is False)):
            raise PayPalError(f"{tool_name} failed: {json.dumps(data)[:300]}")
        return data


# --------------------------------------------------------------------------
# HELPERS TO READ PAYPAL'S ANSWERS
# --------------------------------------------------------------------------
def find_approval_url(order: dict) -> str:
    """
    A new PayPal order contains a list of "links". One of them is the page where
    the HUMAN approves the payment. PayPal names it "payer-action" or "approve".
    """
    for link in order.get("links", []):
        if link.get("rel") in ("payer-action", "approve"):
            return link["href"]
    raise PayPalError("PayPal order has no approval link")


def find_capture_id(result: dict) -> str:
    """
    After pay_order, the "capture id" is the PayPal Transaction ID.
    It is buried at:  purchase_units[0].payments.captures[0].id
    pay_order wraps the PayPal answer as {"status": "success", "response": {...}}.
    """
    body = result.get("response", result)
    try:
        capture = body["purchase_units"][0]["payments"]["captures"][0]
    except (KeyError, IndexError, TypeError):
        raise PayPalError("PayPal answer contained no capture")
    if "COMPLETED" not in str(capture.get("status", "")).upper():
        raise PayPalError(f"Capture is not completed (status: {capture.get('status')})")
    return str(capture["id"])


# --------------------------------------------------------------------------
# WEBHOOK CHECK (REST, because the MCP server has no tool for this)
# --------------------------------------------------------------------------
async def verify_webhook(headers: dict, raw_body: bytes) -> bool:
    """
    PayPal calls OUR server to say "an order was approved". Anyone could fake
    that call to get a free purchase, so we ask PayPal: "did you send this?"
    """
    # For local testing only. NEVER set this to true in real use.
    if os.getenv("PAYPAL_SKIP_WEBHOOK_VERIFY", "false").lower() == "true":
        print("[paypal] WARNING: webhook check skipped (testing mode)")
        return True

    webhook_id = os.getenv("PAYPAL_WEBHOOK_ID", "")
    if not webhook_id:
        print("[paypal] PAYPAL_WEBHOOK_ID is not set, rejecting webhook")
        return False

    h = {key.lower(): value for key, value in headers.items()}
    try:
        token = await get_access_token()
        async with httpx.AsyncClient(timeout=15) as client:
            check = await client.post(
                f"{_api_base()}/v1/notifications/verify-webhook-signature",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "auth_algo": h.get("paypal-auth-algo"),
                    "cert_url": h.get("paypal-cert-url"),
                    "transmission_id": h.get("paypal-transmission-id"),
                    "transmission_sig": h.get("paypal-transmission-sig"),
                    "transmission_time": h.get("paypal-transmission-time"),
                    "webhook_id": webhook_id,
                    "webhook_event": json.loads(raw_body),
                },
            )
            check.raise_for_status()
            return check.json().get("verification_status") == "SUCCESS"
    except Exception as error:
        print(f"[paypal] webhook check failed: {error}")
        return False  # when unsure, say NO
