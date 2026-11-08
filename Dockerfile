# Dockerfile for the WHOLE of PalCart in ONE container (page + Python server + PayPal MCP server)
# =====================================================================
# A Dockerfile is a recipe for a "box" that has everything the app needs.
# PalCart's backend needs TWO languages:
#   - Python  -> our FastAPI server and the AI agent
#   - Node.js -> the official PayPal MCP server (@paypal/mcp)
# So we start from a Node image and add Python on top.

# ---- Stage 1: turn the React page into plain web files ----
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm install
COPY frontend ./
# Empty = the page talks to the same address it was loaded from.
ENV VITE_API_URL=""
RUN npm run build

# ---- Stage 2: the server (it also hands out the web files) ----
FROM node:20-slim

# 1. Install Python (apt is Debian's app installer).
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. Install the PayPal MCP server once, now, so the first request isn't slow.
RUN npm install -g @paypal/mcp

# 3. Make a private Python environment and put it first on the PATH.
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# 4. Install the Python packages. (Done BEFORE copying our code, so Docker can
#    re-use this slow step when only our code changes.)
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --default-timeout=300 --retries 10 -r backend/requirements.txt

# 5. Copy our code. (Your .env file is NOT copied: see .dockerignore.
#    Keys are given to the container when it starts, never baked into the image.)
COPY backend ./backend
COPY agent ./agent
# The built page. The Python server hands these files out at the main address.
COPY --from=web /web/dist ./frontend_dist

# Tell our code to use the PayPal MCP server we installed above.
# The full path avoids mixing it up with a Python command that is also called "mcp".
ENV PAYPAL_MCP_COMMAND="/usr/local/bin/mcp --tools=orders.create,orders.capture,orders.get"

# Hosts like Render tell us which port to use through the PORT variable.
ENV PORT=8000
EXPOSE 8000

# Start the server. ONE worker only: orders live in memory.
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT}"]
