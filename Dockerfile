# Dockerfile for the PalCart BACKEND (Python server + PayPal MCP server)
# =====================================================================
# A Dockerfile is a recipe for a "box" that has everything the app needs.
# PalCart's backend needs TWO languages:
#   - Python  -> our FastAPI server and the AI agent
#   - Node.js -> the official PayPal MCP server (@paypal/mcp)
# So we start from a Node image and add Python on top.

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

# Tell our code to use the PayPal MCP server we installed above.
# The full path avoids mixing it up with a Python command that is also called "mcp".
ENV PAYPAL_MCP_COMMAND="/usr/local/bin/mcp --tools=orders.create,orders.capture,orders.get"

# Hosts like Render tell us which port to use through the PORT variable.
ENV PORT=8000
EXPOSE 8000

# Start the server. ONE worker only: orders live in memory.
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT}"]
