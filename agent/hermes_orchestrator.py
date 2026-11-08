"""
hermes_orchestrator.py  -  THE AI AGENT (LiteLLM + PayPal MCP tools)
====================================================================

The agent works in TWO PHASES. In both, the AI calls tools from three sponsors:

  PHASE 1: "find and prepare"       (starts when the user types a request)
      search_products   -> Channel3   (our function)
      create_order      -> PayPal MCP (the OFFICIAL PayPal tool, used natively)
      ...then we STOP and wait for the human to approve on PayPal.

  PHASE 2: "finish the purchase"    (starts after the human approved)
      get_order               -> PayPal MCP  (check the order is APPROVED)
      pay_order               -> PayPal MCP  (capture the money)
      run_merchant_checkout   -> KERNEL      (cloud browser buys the item)

HOW A TOOL LOOP WORKS
    The AI can't run code. It asks, we run, we answer:
        AI -> us : "please call create_order with these arguments"
        us       : (we call the PayPal MCP server)
        us -> AI : "here is the result"
    WE stay in control. The AI only asks; our code decides.

GUARDRAILS (why a confused or tricked AI can't hurt you)
    * The AI may fill in the create_order arguments, but we CHECK them against
      the Channel3 results and REPLACE name/price with the trusted values.
      The AI can't make up a price, buy a different item, or buy two things.
    * pay_order and get_order always use the REAL order id (we ignore what the AI typed).
    * run_merchant_checkout refuses to run unless the money was captured.
    * PayPal itself refuses to capture an order the human has not approved.

WHY LITELLM
    One function, acompletion(), works with many AI providers. Switching
    between Gemini and a local model is just LLM_PROVIDER in .env.
"""

import json
import os

import litellm

from backend.channel3_client import search_products
from backend.paypal_checkout import find_approval_url

litellm.drop_params = True  # quietly ignore options a provider doesn't support
MAX_STEPS = 8  # safety: the loop can never run forever


# --------------------------------------------------------------------------
# 1. CHOOSE THE AI MODEL (Gemini or local)
# --------------------------------------------------------------------------
def get_model_settings() -> dict:
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider == "gemini":
        # LiteLLM reads GEMINI_API_KEY from the environment by itself.
        return {"model": os.getenv("GEMINI_MODEL", "gemini/gemini-1.5-flash")}

    if provider == "omlx":
        # A local server with an "OpenAI style" API. LiteLLM uses the
        # "openai/" prefix for those, plus the address of our server.
        return {
            "model": "openai/" + os.getenv("OMLX_MODEL", "local-model"),
            "api_base": os.getenv("OMLX_BASE_URL", "http://localhost:8080/v1"),
            "api_key": os.getenv("OMLX_API_KEY", "omlx-local"),
        }

    raise ValueError(f"LLM_PROVIDER must be 'gemini' or 'omlx', got '{provider}'")


# --------------------------------------------------------------------------
# 2. TOOL DESCRIPTIONS FOR THE AI
#    Every tool needs a JSON "schema" that says which arguments it takes.
#    This forces the AI to answer in a strict, correct shape.
# --------------------------------------------------------------------------

# Some AI providers (Gemini!) reject schema keywords they don't know.
# PayPal's schemas contain a few of them, so we remove those keywords.
UNSUPPORTED_KEYWORDS = {
    "additionalProperties", "$schema", "default", "pattern",
    "maxItems", "minLength", "maxLength",
}


def clean_schema(node):
    """Walk through a schema and drop the keywords above."""
    if isinstance(node, dict):
        return {k: clean_schema(v) for k, v in node.items() if k not in UNSUPPORTED_KEYWORDS}
    if isinstance(node, list):
        return [clean_schema(item) for item in node]
    return node


async def paypal_tool(paypal, tool_name: str, keep_fields: list[str]) -> dict:
    """
    Build an AI tool description from the REAL PayPal MCP tool.
    We ask the MCP server for its schema (so it always matches PayPal's version)
    and keep only the fields we want the AI to fill in.
    """
    info = (await paypal.tool_schemas())[tool_name]
    schema = info["schema"]
    kept = {k: v for k, v in schema.get("properties", {}).items() if k in keep_fields}
    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": info["description"].strip().split("\n\n")[0],
            "parameters": clean_schema(
                {
                    "type": "object",
                    "properties": kept,
                    "required": [r for r in schema.get("required", []) if r in kept],
                }
            ),
        },
    }


SEARCH_TOOL = {  # our Channel3 tool
    "type": "function",
    "function": {
        "name": "search_products",
        "description": "Search for products to buy (Channel3). Returns ids, titles, prices and whether the shop allows guest checkout.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "max_price": {"type": "number", "description": "Price limit in USD, if given"},
            },
            "required": ["query"],
        },
    },
}

CHECKOUT_TOOL = {  # our KERNEL tool
    "type": "function",
    "function": {
        "name": "run_merchant_checkout",
        "description": (
            "Use the KERNEL cloud browser to buy the item on the merchant's website. "
            "Only works AFTER pay_order succeeded."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

PHASE1_PROMPT = """You are PalCart, a careful shopping assistant.
1. Call search_products for what the user wants. Respect any price limit.
2. Pick the single best match for what the user asked for (the title must really match).
   All products come from trusted shops that let our robot buy WITHOUT an account.
   Among the matching products, choose the cheapest.
3. Call create_order (PayPal) with:
   - currencyCode: "USD"
   - exactly ONE item: name = the product title, itemCost = its price, quantity = 1,
     itemTotal = its price, description = the product's id (for example "P1").
4. Then tell the user, in one or two short sentences, to approve the payment on PayPal.
Rules:
- Only use products from search results. Never invent products or prices.
- If nothing matches, say so and do NOT create an order.
- You never handle card details. The human pays on PayPal."""

PHASE2_PROMPT = """You are PalCart finishing an order that a human has approved on PayPal.
Do these steps IN ORDER:
1. Call get_order to check the order status.
2. If the status is APPROVED, call pay_order to capture the payment.
3. After pay_order succeeds, call run_merchant_checkout.
4. Reply with ONE short sentence saying how it went.
If any step fails, stop and say what failed. Never call run_merchant_checkout before pay_order succeeds."""


# --------------------------------------------------------------------------
# 3. THE GENERIC TOOL LOOP (used by both phases)
# --------------------------------------------------------------------------
async def tool_loop(messages: list, tools: list, execute_tool) -> str:
    """
    Keep asking the AI what to do until it stops requesting tools.

    execute_tool(name, args) -> dict   runs ONE tool and returns its result.
    Returns the AI's final text answer.
    """
    final_text = ""

    for step in range(MAX_STEPS):
        response = await litellm.acompletion(
            messages=messages,
            tools=tools,
            temperature=0,  # 0 = most predictable
            **get_model_settings(),
        )
        ai_message = response.choices[0].message
        tool_calls = ai_message.tool_calls or []
        final_text = ai_message.content or final_text

        if not tool_calls:
            break  # a normal answer: we are done

        # Remember what the AI asked for (it needs to see this next round).
        messages.append(
            {
                "role": "assistant",
                "content": ai_message.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.function.name, "arguments": call.function.arguments},
                    }
                    for call in tool_calls
                ],
            }
        )

        # Run each requested tool and send the result back.
        for call in tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except ValueError:
                args = {}  # broken JSON from the AI; the tool will complain
            try:
                result = await execute_tool(call.function.name, args)
            except Exception as error:  # a failing tool must not crash the loop
                result = {"error": str(error)}
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
            )

    return final_text


# --------------------------------------------------------------------------
# 4. PHASE 1: FIND THE PRODUCT AND CREATE THE PAYPAL ORDER
# --------------------------------------------------------------------------
async def run_shopping_agent(user_request, paypal, save_order, return_url, cancel_url) -> dict:
    """
    paypal      : the PayPalMCP client (paypal_checkout.py)
    save_order  : a function from app.py that saves the new order for the dashboard.
                  save_order(product, paypal_order_id, approval_url) -> our order id

    Returns {"message": "text for the user", "order_id": "..." or None}
    """
    max_usd = float(os.getenv("MAX_ORDER_USD", "50"))
    catalog: dict[str, dict] = {}  # trusted products from the latest search, by short id
    created = {"order_id": None}

    async def execute_tool(name: str, args: dict) -> dict:
        # ---------------- Channel3: search ----------------
        if name == "search_products":
            products = await search_products(args.get("query", ""), args.get("max_price"))
            catalog.clear()
            for number, product in enumerate(products, start=1):
                catalog[f"P{number}"] = product  # short ids: P1, P2, ...
            if not catalog:
                return {"products": [], "note": "No product from a trusted shop matched. Tell the user, and do NOT create an order."}
            return {
                "products": [
                    {"id": pid, "title": p["title"], "merchant": p["merchant"],
                     "price": p["price"], "currency": p["currency"],
                     "guest_checkout": p["guest_checkout"]}
                    for pid, p in catalog.items()
                ]
            }

        # ---------------- PayPal MCP: create_order ----------------
        if name == "create_order":
            if created["order_id"]:
                return {"error": "An order was already created"}

            # GUARDRAIL: find which trusted product the AI is talking about.
            items = args.get("items") or []
            if len(items) != 1:
                return {"error": "Order exactly ONE item"}
            product = catalog.get(str(items[0].get("description", "")).strip())
            if not product:
                return {"error": "Put the product id (like P1) from search_products in the item's description"}
            if product["currency"] != "USD":
                return {"error": "The PayPal tool only supports USD"}
            if product["price"] > max_usd:
                return {"error": f"Price is above our ${max_usd} limit"}

            # GUARDRAIL: ignore the AI's name/price. Use OUR trusted values.
            trusted_args = {
                "currencyCode": "USD",
                "items": [
                    {
                        "name": product["title"][:127],
                        "quantity": 1,
                        "itemCost": product["price"],
                        "itemTotal": product["price"],
                        "description": items[0]["description"],
                    }
                ],
                # Where PayPal sends the human after approving / cancelling.
                "returnUrl": return_url,
                "cancelUrl": cancel_url,
            }

            # THE REAL PAYPAL CALL: the official MCP tool creates an order with intent CAPTURE.
            order = await paypal.call("create_order", trusted_args)

            created["order_id"] = save_order(product, order["id"], find_approval_url(order))
            return {"status": "waiting for the human to approve on PayPal"}

        return {"error": f"Unknown tool {name}"}

    messages = [
        {"role": "system", "content": PHASE1_PROMPT},
        {"role": "user", "content": user_request},
    ]
    tools = [SEARCH_TOOL, await paypal_tool(paypal, "create_order", ["currencyCode", "items"])]
    text = await tool_loop(messages, tools, execute_tool)

    if created["order_id"] and not text:
        text = "Order created. Please approve the payment on PayPal."
    return {"message": text or "Sorry, I could not complete that request.", "order_id": created["order_id"]}


# --------------------------------------------------------------------------
# 5. PHASE 2: AFTER APPROVAL, CAPTURE THE MONEY AND BUY THE ITEM
# --------------------------------------------------------------------------
async def run_checkout_agent(order: dict, paypal, capture_payment, run_checkout) -> str:
    """
    order           : the order dictionary (from app.py)
    capture_payment : app.py function that calls PayPal MCP pay_order and records the result
    run_checkout    : app.py function that runs the KERNEL browser (refuses if unpaid)
    """

    async def execute_tool(name: str, args: dict) -> dict:
        # NOTE: we ignore any "id" the AI typed and always use the REAL order id.
        if name == "get_order":
            details = await paypal.call("get_order", {"id": order["paypal_order_id"]})
            return {"order_status": details.get("status")}  # e.g. APPROVED

        if name == "pay_order":
            return await capture_payment(order)

        if name == "run_merchant_checkout":
            return await run_checkout(order)

        return {"error": f"Unknown tool {name}"}

    messages = [
        {"role": "system", "content": PHASE2_PROMPT},
        {
            "role": "user",
            "content": (
                f"Order {order['order_id']} ('{order['item_name']}') was approved by the human. "
                f"The PayPal order id is {order['paypal_order_id']}. Please finish it."
            ),
        },
    ]
    tools = [
        await paypal_tool(paypal, "get_order", ["id"]),
        await paypal_tool(paypal, "pay_order", ["id"]),
        CHECKOUT_TOOL,
    ]
    return await tool_loop(messages, tools, execute_tool)
