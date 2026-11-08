# PalCart: roadmap, known limits and fixes before hosting

Tick the boxes as you go.
**P0** = do before hosting. **P1** = do before the demo or submission. **P2** = nice to have.
"(I can do this)" means it is a code change Claude can make for you.

---

## 1. Hosting on Render (P0)

- [x] **Frontend address.** DONE: the page now uses relative `/api` addresses (Vite proxy locally, nginx in Docker), or `VITE_API_URL` when the frontend is hosted separately.
- [ ] **Remove or protect the debug routes** `/api/channel3/test` and `/api/paypal/tools`. They are open to everyone, and errors from them can show the first characters of your key. (I can do this)
- [ ] **Add an access code** (or a rate limit) on `/api/agent/run`, so strangers can't use up your Gemini, Channel3 and KERNEL credits. Give the code to the judges in your submission. (I can do this)
- [x] **Dockerfile** with Python and Node.js. DONE: `Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`. Not yet tested with a real `docker compose up` (the build sandbox had no Docker engine).
- [ ] **Set the real addresses:** `PUBLIC_BASE_URL` = your Render backend address, `FRONTEND_URL` = your frontend address.
- [ ] **PayPal webhook:** in the PayPal sandbox app, add `<backend address>/api/paypal/webhook`, copy the webhook ID into `PAYPAL_WEBHOOK_ID`, and keep `PAYPAL_SKIP_WEBHOOK_VERIFY=false`.
- [ ] **Use Gemini on the hosted version** (`LLM_PROVIDER=gemini`). A hosted server can't reach the model on your laptop.
- [ ] **Check the Gemini model name.** `gemini/gemini-1.5-flash` may be retired. Set `GEMINI_MODEL` to a current model and test it.
- [ ] **Run one worker only.** Orders live in memory, so several workers would each have their own copy.
- [ ] **Free plans sleep.** Open the app a few minutes before judges do, or use a plan that stays awake.
- [ ] **Keys go in Render's Environment settings only.** Never in code, never in GitHub.
- [ ] **Keep test settings on:** `PAYPAL_MODE=sandbox`, `KERNEL_DRY_RUN=true`, low `MAX_ORDER_USD`, no real card.
- [ ] **Set usage limits** in the Gemini, Channel3 and KERNEL dashboards if they allow it. Replace the keys after the hackathon.

## 2. The shopping robot (KERNEL) (P0/P1)

- [ ] **P0: Pick ONE demo shop that allows guest checkout** (a simple Shopify-style store works best) and tune the robot for its exact buttons. Test it in a private browser window first.
- [x] **P0: Guest-checkout shop ranking.** DONE: guest-friendly shops come first and account-only shops are skipped (`backend/guest_checkout_sites.py`, plus `EXTRA_GUEST_CHECKOUT_SITES` in `.env`). Still to do: an option to ONLY allow listed shops.
- [ ] **P0: Make the status honest.** In dry run the robot says "Execution Complete" even if it filled in nothing. Check that the key fields were filled, and mark the order Failed if not. (I can do this)
- [ ] P1: Fill in the delivery details in `.env`: `SHIP_NAME`, `SHIP_EMAIL`, `SHIP_ADDRESS`, `SHIP_CITY`, `SHIP_ZIP`. Add `SHIP_COUNTRY`, `SHIP_STATE`, `SHIP_PHONE` and robot steps for them. (I can do this)
- [ ] P1: Handle common page problems: size or colour pickers, "pick up in store" only items, cookie pop-ups, "sign in to continue" pages.
- [ ] P1: Show the live view link and the failure screenshot in the dashboard, not only in the terminal. (I can do this)
- [ ] P1: Add one overall time limit for the whole checkout, so an order can't stay on "Executing" for long. (I can do this)
- [ ] P2: Expect big shops to block robots (bot protection). Say so honestly in your write-up.
- [ ] P2: Screenshots saved on Render disappear when it restarts. Upload them somewhere if you want to keep them.

## 3. Payments and safety (P1)

- [ ] **Failed checkout after payment.** The payment is already captured, so a failed robot leaves a paid order. Options: add a refund step (needs the PayPal refund tool switched on in the MCP server), or only capture after the checkout is confirmed to work. The second one is a design change from `intent: CAPTURE`, so talk it through before you change it.
- [ ] Only USD works with the PayPal MCP `create_order` tool. Say so clearly, and refuse other currencies with a friendly message.
- [ ] Use the **US sandbox buyer** account. An Indian buyer account gives "seller doesn't accept payments in your currency".
- [ ] Keep one PayPal sandbox buyer login ready for the judges (put it in the submission form, not in the public repo).
- [ ] Add a hard daily order limit (for example 5 orders), so a loop or a bad actor can't create hundreds of orders. (I can do this)

## 4. The agent (P1/P2)

- [ ] **P1: Ask the user to confirm the product** before creating the PayPal order ("I found X for $Y. Buy it?"). Right now the agent picks the cheapest match on its own. (I can do this)
- [ ] P1: Better product choice. "Cheapest" isn't "best". Let the agent prefer well-matching titles, or show 3 options to choose from. (I can do this)
- [ ] P1: Ask for the delivery address in the dashboard for each order instead of one fixed address in `.env`. (I can do this)
- [ ] P2: Start the PayPal MCP server once and keep it running. It currently starts fresh for each call, which costs about a second each time.
- [ ] P2: Support quantity greater than 1 and several items in one order.
- [ ] P2: Keep the local model (oMLX) option for local demos only, and say so in the README.

## 5. Data (P1)

- [ ] **Orders are lost when the server restarts.** Move the orders to a small database (SQLite file, or Postgres on Render). (I can do this)
- [ ] The dashboard shows everyone's orders to everyone. Fine for a demo, but mention it, or show only your own orders.

## 6. Frontend polish (P2)

- [ ] Press Enter to submit the request, and show a clear error if the backend can't be reached.
- [ ] Keep a short history of agent replies on the page.
- [ ] Make the table fit narrow screens and show the newest order at the top (already sorted).
- [ ] Show a clear "Approve on PayPal" button next to the new order after the agent replies.

## 7. GitHub readiness (P0/P1)

- [ ] **P0: Check that `.env` is not in the repo** (and never was in its history). If a key was ever committed, replace the key.
- [x] P0: Make sure `.gitignore` covers `.env`, `artifacts/`, `node_modules/`, `__pycache__/`, `.venv/`, `dist/`.
- [ ] P0: Update `.env.example` with every setting you use (`KERNEL_HEADLESS`, `ALLOWED_MERCHANTS`, the access code, and so on). Use placeholder values only.
- [ ] P1: **README:** add the hosted link, your demo video link, a screenshot or GIF, the architecture picture, and "how judges can test it" in 3 steps.
- [x] P1: Add a `LICENSE` file (MIT is common for hackathons).
- [x] P1: Add a few automated tests (the fake-LLM test from this project is a good start) in a `tests/` folder.
- [ ] P1: Pin versions in `requirements.txt` and `package.json`, and note the Python and Node versions.
- [ ] P1: Add a `render.yaml` (Render blueprint) so the backend can be deployed in one click. (I can do this)
- [x] P2: Add a simple GitHub Action that runs the tests.
- [ ] P2: Add the `IMPROVEMENTS.md` file itself as "Roadmap / known limits". Judges like honest limits.

## 8. Demo and submission (P1)

- [ ] Rehearse ONE prompt 3 to 5 times (for example "Find a LEGO set for my nephew's birthday, under $30") and keep the one that works every time.
- [ ] Record the real flow: ask, approve on PayPal, watch the robot in live view, see Execution Complete. Use it in place of the sample dashboard in the 2:30 video.
- [ ] Say "PayPal test mode" and "dry run" out loud. Honest framing builds trust.
- [ ] Keep the recorded video as a backup for the live demo.
- [ ] End with the "one more thing": switch to a local model with one setting.

## 9. Known limits to state honestly in your submission

- Sandbox payments only. The robot stops before the final pay button (dry run).
- USD only. One fixed delivery address. Orders stored in memory.
- The robot works best on simple shops with guest checkout. Big shops may block it.
- If the robot fails after payment, a human has to refund it.
