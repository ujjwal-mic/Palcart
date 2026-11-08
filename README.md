# PalCart: Agentic PayPal Orchestrator

An AI shopping agent. You tell it what you want (by typing or by voice), it finds the product and prepares the purchase. **A human must approve the payment on PayPal before the AI is allowed to buy anything.** The AI never sees card data.

Built for the PayPal AI Hackathon 2026.

## How it works

1. You say or type a request, for example "Find a wireless keyboard for the office under $30".
2. **Agent, part 1.** The AI searches products with **Channel3**. Only trusted shops that allow guest checkout are used. Then it calls the official **PayPal MCP server** (`create_order`, `intent: CAPTURE`) to prepare an order.
3. You click **Approve on PayPal** and pay in PayPal's own page.
4. **Agent, part 2.** The AI calls PayPal MCP again (`get_order`, `pay_order`) to capture the money, then a **KERNEL** cloud browser (driven by Playwright over CDP) does the shop checkout.
5. The **AG Grid** dashboard shows every step live. When an order completes, you get a party popper.

Golden rule: the cloud browser only runs after the money is captured. This is enforced in code, not only in the AI's instructions.

## Architecture

```
 You (type or voice)
        |
        v
  React + AG Grid dashboard  <------------ polls /api/orders every 3 s
        |  /api
        v
  FastAPI backend ---- Channel3 .............. finds products (trusted shops only)
        |
        +---- AI agent (LiteLLM: Gemini or a local model)
        |        |
        |        +-- PayPal MCP server (@paypal/mcp): create_order -> get_order -> pay_order
        |
        +---- KERNEL cloud browser (Playwright over CDP): buys from the shop,
              only AFTER the money is captured
```

| Sponsor tool | What PalCart uses it for |
|---|---|
| **PayPal** (official MCP server) | Creates the order (intent CAPTURE), checks it, captures the money |
| **Channel3** | Product search across shops |
| **KERNEL** | Cloud browser that completes the shop checkout |
| **AG Grid** | The live "Procurement Log" dashboard |

## Quick start

You need [Docker](https://www.docker.com/products/docker-desktop/) and five free or sandbox API keys (see [The 5 keys you need](#the-5-keys-you-need)).

1. **Configure and start.** Copy the settings file, put your five keys at the top of `.env`, and start everything with one command:
   ```bash
   cp .env.example .env
   docker compose up --build
   ```
2. **Place a request.** Open <http://localhost:3000> (use <http://localhost:5173> if you run it without Docker), then type or say:
   > Find a wireless keyboard for the office under $30

   Click **Approve on PayPal** and pay with a **US sandbox buyer** account.
3. **Watch it run.** The order moves through *Pending Authorization → Payment Captured → Executing Checkout → Execution Complete*, with confetti at the end.

> **Sandbox and dry run:** payments use PayPal's sandbox (test money), and the checkout robot runs in dry-run mode. It fills in the shop's checkout but stops before the final pay button, so nothing real is bought.

## Run it with Docker (easiest)

You need [Docker](https://www.docker.com/products/docker-desktop/) installed.

```bash
# 1. Make your settings file
cp .env.example .env          # Windows: copy .env.example .env

# 2. Open .env and fill in the 5 keys at the top (see the table below)

# 3. Start everything
docker compose up --build
```

Open **http://localhost:3000**. That is the whole setup. Stop it with `Ctrl+C`.

## Run it without Docker

You need Python 3.10+ and Node.js 18+ (the PayPal MCP server runs on Node and starts by itself).

```bash
# Backend (terminal 1, inside the project folder)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cp .env.example .env             # then fill in the 5 keys at the top
uvicorn backend.app:app --reload --port 8000
```

```bash
# Frontend (terminal 2)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Run `uvicorn` from the project folder (the imports depend on it). The first PayPal call is slow while `npx` downloads the PayPal MCP server.

## The 5 keys you need

Put them at the top of `.env`. Everything else in that file has a working default.

| Key in `.env` | What it is for | Where to get it |
|---|---|---|
| `CHANNEL3_API_KEY` | Product search | Channel3 (hackathon sponsor) |
| `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` | PayPal sandbox payments | developer.paypal.com, create a Sandbox app |
| `KERNEL_API_KEY` | The cloud browser robot | dashboard.onkernel.com |
| `GEMINI_API_KEY` | The AI brain | aistudio.google.com/apikey (free) |

After you edit `.env`, restart the server (`Ctrl+C`, then start it again).

## Try it

1. Type "Find a wireless keyboard for the office under $30" and press **Ask agent**, or click the microphone and say it.
2. A new row appears as "Pending Authorization". Click **Approve on PayPal**.
3. Pay with a PayPal **sandbox buyer** account. Create it as a **Personal** account with the country set to **United States**. A buyer from another country gets "seller doesn't accept payments in your currency", because PalCart's PayPal tool works in USD.
4. You come back to the dashboard. The status goes to Payment Captured, then Executing Checkout, then Execution Complete, and confetti fires.

By default `KERNEL_DRY_RUN=true`, so the robot fills in the shop checkout but does **not** press the final pay button. Nothing real is bought. While it works, look in the terminal for a `WATCH LIVE` link to watch the robot.

## Voice input (no API key)

Click the microphone and speak. This uses the speech feature built into your browser, so it needs no key and no account.

- Works in Chrome, Edge and Safari. Firefox does not support it.
- The browser asks for microphone permission the first time.
- It needs internet (the browser sends audio to its own speech service) and only works on `https://` pages or `localhost`.
- By default, your request is sent when you stop speaking. Untick "Send automatically" to check the text first.

## Pictures and replays

- Every order shows a **picture of the item** being bought.
- The `WATCH LIVE` link is printed in the terminal while the robot works.
- Optional: set `ORDER_VIDEO=true` in `.env` to record every order. The replay of an order is then at `http://localhost:3000/api/orders/<ORDER ID>/replay` (saved in the `artifacts/replays` folder). It is off by default.

## Trusted shops only

The robot can't log in, and many small online shops look real but have broken checkouts (or are not real stores). So PalCart **only buys from a trusted list of shops that allow guest checkout** (see `backend/guest_checkout_sites.py`). Shops that need an account (Amazon, Costco) and shops that are not on the list are skipped. If no trusted shop sells what you asked for, the agent says so and creates no order.

- Add a shop you tested yourself: `EXTRA_GUEST_CHECKOUT_SITES=myshop.com` in `.env`.
- Allow unknown shops anyway (not recommended): `ALLOW_UNKNOWN_SHOPS=true`.
- The list is a best guess. Test a shop in a private browser window before you rely on it.

## Safety features

- The AI can only ask for an order. A human pays on PayPal's own page.
- Prices and links come from Channel3 data. Our code replaces whatever name or price the AI typed.
- `MAX_ORDER_USD` is a spending limit enforced in code.
- PayPal webhooks are verified with PayPal, so nobody can fake a payment.
- One payment can only trigger one checkout.
- The robot refuses to run unless the money is captured.
- Card and delivery details come from `.env` and are never shown to the AI.
- Only three PayPal tools are switched on (`create_order`, `get_order`, `pay_order`).

## Troubleshooting

| What you see | What it means |
|---|---|
| "Channel3 rejected the API key" | `CHANNEL3_API_KEY` is wrong or still the placeholder. Fix `.env` and restart. |
| "Could not start KERNEL browser: Invalid or disabled API key" | `KERNEL_API_KEY` is wrong or disabled. Get a new one in the KERNEL dashboard. |
| "Could not find an 'Add to cart' button" | The shop's page is laid out differently (or blocks robots). The Notes column lists the buttons the robot saw. Try a simpler shop. |
| PayPal says "seller doesn't accept payments in your currency" | Use a US sandbox buyer account (see "Try it"). |
| Open http://localhost:8000/api/paypal/tools (without Docker) | Should list `create_order`, `get_order`, `pay_order` if PayPal MCP is set up right. |

## Tests

```bash
pip install pytest
python -m pytest tests
```

These tests need no internet and no API keys. They check the shop filter, the ranking and the picture parsing.

## Known limits

- Everything runs in PayPal **sandbox** mode with the robot in dry-run mode. It is a demo, not a store.
- Orders are kept in memory. Restarting the server clears them.
- Only USD works. One fixed delivery address (from `.env`).
- The robot works best on simple shops. Big shops may need a login, show pop-ups, or block robots.
- If the robot fails after PayPal took the money, the order is marked Failed with a note. Refunds are not automated.

## Project layout

| File | Job |
|---|---|
| `backend/app.py` | The main server. Start reading here. |
| `backend/paypal_checkout.py` | Talks to the official PayPal MCP server |
| `backend/channel3_client.py` | Product search and ranking |
| `backend/guest_checkout_sites.py` | Which shops allow guest checkout |
| `agent/hermes_orchestrator.py` | The AI agent loop (LiteLLM) |
| `agent/kernel_cdp.py` | The cloud browser robot, live view and recording |
| `frontend/src/App.jsx` | The page: text box, microphone |
| `frontend/src/components/ProcurementGrid.jsx` | The AG Grid dashboard and confetti |
| `Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` | Run everything with one command |
| `tests/` | Small tests (no keys needed) |
| `.env.example` | Template for your keys and settings |

## More

- `IMPROVEMENTS.md` lists the known gaps and the roadmap.
- License: MIT (see `LICENSE`).
