"""
app.py  -  THE MAIN SERVER (FastAPI)
====================================

This file connects everything together. Read it top to bottom!

THE WHOLE STORY (follow the numbers)

  1. User sends a request              ->  POST /api/agent/run
  2. AGENT PHASE 1: searches Channel3, then calls the PayPal MCP tool
     create_order (intent CAPTURE). Order status: pending_authorization
  3. Human clicks the PayPal link and approves
  4. PayPal tells us ("webhook")       ->  POST /api/paypal/webhook
     (or sends the human back to us    ->  GET  /api/paypal/return)
  5. AGENT PHASE 2 (in the background):
        get_order (PayPal MCP)   -> is it APPROVED?
        pay_order (PayPal MCP)   -> capture the money   (status: payment_captured)
        run_merchant_checkout    -> KERNEL cloud browser (status: executing -> execution_complete)
  6. The dashboard reads the orders    ->  GET  /api/orders

THE GOLDEN RULE
    The KERNEL browser only runs after the money is captured. This is enforced
    in CODE (see run_checkout below), not just in the AI's instructions.
"""

import asyncio
import html
import json
import os
import re
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

# Load the secret keys from the .env file into the environment.
# This must happen BEFORE we import our other files.
load_dotenv()

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from agent.hermes_orchestrator import run_checkout_agent, run_shopping_agent  # noqa: E402
from agent.kernel_cdp import CheckoutError, buy_from_merchant, replay_file  # noqa: E402
from backend import paypal_checkout  # noqa: E402
from backend.paypal_checkout import PayPalMCP, PayPalError  # noqa: E402

# --------------------------------------------------------------------------
# SETTINGS (from .env)
# --------------------------------------------------------------------------
# PUBLIC_BASE_URL = where PayPal can reach THIS server.
# FRONTEND_URL    = where the React dashboard runs.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

# The client for the official PayPal MCP server (see paypal_checkout.py).
paypal = PayPalMCP()

# --------------------------------------------------------------------------
# THE "DATABASE"
# A plain Python dictionary is enough for a hackathon.
#   key   = our order id, like "A1B2C3D4E5"
#   value = a dictionary describing the order
# WARNING: it lives in memory, so restarting the server erases it.
# --------------------------------------------------------------------------
ORDERS: dict[str, dict] = {}

# The possible statuses (plain text, easy to show in the dashboard).
PENDING = "pending_authorization"  # waiting for the human to pay
CAPTURED = "payment_captured"  # money received
EXECUTING = "executing"  # robot is buying the item
COMPLETE = "execution_complete"  # done!
FAILED = "failed"  # something broke (see "detail")

# Orders whose "finish" job has already started. This stops the webhook AND
# the return page from both starting the same job (which could buy twice!).
started_orders: set[str] = set()

# Background tasks. We keep them in a set so Python doesn't throw them away.
background_tasks: set = set()

app = FastAPI(title="PalCart")

# CORS: browsers block a web page from calling a different address unless the
# server allows it. We allow our React dashboard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_URL, "http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentRequest(BaseModel):
    prompt: str


@app.get("/api/health")
async def health():
    """A simple "is the server alive?" check."""
    return {"status": "ok", "llm_provider": os.getenv("LLM_PROVIDER", "gemini")}


@app.get("/api/channel3/test")
async def channel3_test(q: str = "lego set", max_price: float | None = None):
    """
    Test Channel3 on its own, without the AI. Open this in your browser:
        http://localhost:8000/api/channel3/test?q=lego set&max_price=50
    If the search fails, you see the REAL reason here (bad key, wrong URL...).
    """
    from backend.channel3_client import search_products

    try:
        return {"products": await search_products(q, max_price)}
    except Exception as error:
        raise HTTPException(status_code=502, detail=str(error))


@app.get("/api/paypal/tools")
async def paypal_tools():
    """Shows which tools the official PayPal MCP server offers. Good for checking your setup."""
    try:
        tools = await paypal.tool_schemas()
    except PayPalError as error:
        raise HTTPException(status_code=502, detail=str(error))
    return {"mcp_server": "@paypal/mcp", "tools": sorted(tools)}


# ==========================================================================
# ROUTE 1: RUN THE AGENT, PHASE 1  (steps 1-2 of the story)
# ==========================================================================
@app.post("/api/agent/run")
async def agent_run(request: AgentRequest):
    # The agent calls this after PayPal MCP created the order, so we can save it.
    def save_order(product: dict, paypal_order_id: str, approval_url: str) -> str:
        order_id = uuid.uuid4().hex[:10].upper()  # our own short order id
        ORDERS[order_id] = {  # one row in the dashboard
            "order_id": order_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "item_name": product["title"],
            "merchant": product["merchant"],
            "total_price": product["price"],
            "currency": product["currency"],
            "product_url": product["url"],  # trusted: from Channel3, never from the AI
            "image_url": product.get("image_url"),  # the picture of the item being bought
            "live_view_url": None,  # filled in while the robot works (if ORDER_VIDEO=true)
            "replay_url": None,  # filled in when the recording is saved
            "paypal_order_id": paypal_order_id,
            "paypal_transaction_id": None,  # filled in after the money is captured
            "approval_url": approval_url,
            "status": PENDING,
            "detail": "",
        }
        return order_id

    try:
        result = await run_shopping_agent(
            request.prompt,
            paypal,
            save_order,
            return_url=f"{PUBLIC_BASE_URL}/api/paypal/return",
            cancel_url=FRONTEND_URL,
        )
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Agent error: {error}")

    order = ORDERS.get(result["order_id"]) if result["order_id"] else None
    return {"message": result["message"], "order": order}


# ==========================================================================
# ROUTE 2: DATA FOR THE DASHBOARD
# ==========================================================================
@app.get("/api/orders")
async def list_orders():
    """Return all orders, newest first. The AG Grid table calls this."""
    return sorted(ORDERS.values(), key=lambda o: o["created_at"], reverse=True)


# ==========================================================================
# ROUTE 2b: REPLAY OF AN ORDER (a permanent address that never changes)
#   http://localhost:3000/api/orders/<ORDER ID>/replay
# ==========================================================================
ORDER_ID_PATTERN = re.compile(r"^[A-Z0-9]{10}$")  # also stops "../" tricks in the address


def replay_path_for(order_id: str):
    if not ORDER_ID_PATTERN.match(order_id):
        raise HTTPException(status_code=404, detail="No such order")
    return replay_file(order_id)


@app.get("/api/orders/{order_id}/replay.mp4")
async def replay_video(order_id: str):
    path = replay_path_for(order_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="No recording for this order")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/orders/{order_id}/replay")
async def replay_page(order_id: str):
    path = replay_path_for(order_id)
    if not path.exists():
        return HTMLResponse(
            "<h2>No recording (yet)</h2><p>Either this order is still running, or "
            "ORDER_VIDEO was off, or KERNEL could not record it.</p>",
            status_code=404,
        )
    order = ORDERS.get(order_id, {})
    title = html.escape(order.get("item_name", f"Order {order_id}"))
    image = order.get("image_url")
    picture = f'<img src="{html.escape(image)}" alt="" style="height:90px;border-radius:8px;margin-right:14px" referrerpolicy="no-referrer">' if image else ""
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><title>Replay {order_id}</title>"
        "<body style='font-family:system-ui;max-width:960px;margin:24px auto;padding:0 16px'>"
        f"<div style='display:flex;align-items:center'>{picture}<div><h2 style='margin:0'>{title}</h2>"
        f"<p style='margin:4px 0;color:#555'>Order {order_id}: recording of the robot's checkout</p></div></div>"
        f"<video src='/api/orders/{order_id}/replay.mp4' controls autoplay muted style='width:100%;margin-top:16px;border-radius:10px;background:#000'></video>"
        "</body>"
    )


# ==========================================================================
# THE TWO REAL ACTIONS. The agent's tools call these, and so does our safety
# net. Each one checks the order status first, so they are safe to call twice.
# ==========================================================================
async def capture_payment(order: dict) -> dict:
    """Capture the money with the PayPal MCP tool pay_order."""
    if order["status"] != PENDING:
        return {"note": f"Nothing to do, order status is already {order['status']}"}
    try:
        result = await paypal.call("pay_order", {"id": order["paypal_order_id"]})
        order["paypal_transaction_id"] = paypal_checkout.find_capture_id(result)
    except PayPalError as error:
        order["status"] = FAILED
        order["detail"] = f"Payment capture failed: {error}"
        return {"error": order["detail"]}
    order["status"] = CAPTURED
    return {"status": "payment captured", "transaction_id": order["paypal_transaction_id"]}


async def run_checkout(order: dict) -> dict:
    """Buy the item with the KERNEL cloud browser. REFUSES if the money isn't captured."""
    if order["status"] != CAPTURED:  # THE GOLDEN RULE, enforced in code
        return {"error": f"Refused: payment not captured (status is {order['status']})"}

    order["status"] = EXECUTING
    try:
        order["detail"] = await buy_from_merchant(
            order["product_url"], order["order_id"], report=lambda **fields: order.update(fields)
        )
        order["status"] = COMPLETE
    except CheckoutError as error:
        order["status"] = FAILED
        order["detail"] = f"Merchant checkout failed: {error} (customer was charged - needs refund or retry)"
    except Exception as error:
        order["status"] = FAILED
        order["detail"] = f"Unexpected error: {error}"
    return {"status": order["status"], "detail": order["detail"]}


# ==========================================================================
# AGENT PHASE 2: runs in the background after the human approves
# ==========================================================================
async def finish_order(order: dict):
    # First, let the AI agent do it with its tools (get_order, pay_order, KERNEL).
    try:
        answer = await run_checkout_agent(order, paypal, capture_payment, run_checkout)
        print(f"[app] agent says: {answer}")
    except Exception as error:
        print(f"[app] checkout agent problem: {error}")

    # SAFETY NET: if the AI skipped a step (small local models sometimes do),
    # finish the job directly with the same two functions. Demos must not hang!
    if order["status"] == PENDING:
        await capture_payment(order)
    if order["status"] == CAPTURED:
        await run_checkout(order)


async def on_human_approved(paypal_order_id: str):
    """Called when the human has approved. Starts phase 2 exactly once."""
    order = next((o for o in ORDERS.values() if o["paypal_order_id"] == paypal_order_id), None)
    if order is None:
        print(f"[app] unknown PayPal order {paypal_order_id}")
        return
    if order["order_id"] in started_orders:
        return  # the webhook and the return page both fire; only the first counts
    started_orders.add(order["order_id"])

    # Run in the BACKGROUND, so we answer PayPal quickly (it retries if we are slow).
    task = asyncio.create_task(finish_order(order))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


# ==========================================================================
# ROUTE 3: PAYPAL SENDS THE HUMAN BACK HERE AFTER APPROVING
# This makes the demo work even without a public webhook address.
# ==========================================================================
@app.get("/api/paypal/return")
async def paypal_return(token: str):
    # PayPal adds "?token=<paypal order id>" to the address.
    await on_human_approved(token)
    return RedirectResponse(FRONTEND_URL)  # send the human back to the dashboard


# ==========================================================================
# ROUTE 4: THE PAYPAL WEBHOOK
# PayPal's servers call this directly when something happens.
# ==========================================================================
@app.post("/api/paypal/webhook")
async def paypal_webhook(request: Request):
    raw_body = await request.body()

    # SECURITY: make sure this really came from PayPal.
    if not await paypal_checkout.verify_webhook(dict(request.headers), raw_body):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event = json.loads(raw_body)
    print(f"[app] PayPal webhook: {event.get('event_type')}")

    # "CHECKOUT.ORDER.APPROVED" = the human clicked Approve.
    if event.get("event_type") == "CHECKOUT.ORDER.APPROVED":
        await on_human_approved(event["resource"]["id"])

    return {"status": "received"}  # always answer "ok" so PayPal stops retrying
