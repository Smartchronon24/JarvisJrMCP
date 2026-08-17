# JarvisMCP

A minimal yet powerful **Model Context Protocol (MCP)** based AI assistant built on Ollama. Jarvis can remember facts, interact with external services, and chat using large language models — all through a clean plugin-style MCP architecture.

---

## Features
- **Memory MCP** — Persistent graph-based store for entities, observations, and relations.
- **Uber MCP** — OAuth 2.0 + Uber REST API integration. Get price estimates, check ride status.
- **Tool-first architecture** — The LLM follows the exact JSON schema of each MCP tool.
- **Configurable endpoint** — Run against local Ollama or a remote corporate server.
- **Streaming / non-streaming** output mode.
- **Graceful fallback** when a model does not support tools.
- **Extensible** — Add any MCP server by editing one dict in `config/settings.py`.

---

## Repository layout
```
JarvisMCP/
├─ config/
│   └─ settings.py            # Host, model, MCP server map, system prompt
├─ ollama_agent.py             # Main entry point, chat loop, tool dispatch
├─ oauth_callback_server.js    # Uber OAuth callback helper (run separately during auth)
├─ .env.example                # Environment variable template (no real credentials)
├─ data/                       # Memory database (generated at runtime)
├─ .gitignore
└─ README.md
```

---

## Quick Start

### Prerequisites
| Requirement | Version |
|---|---|
| Python | 3.12+ |
| Node.js / npm | 18+ (for npx MCP servers) |
| Ollama | Any recent version |

### 1. Install Python dependencies
```powershell
python -m venv JarvisVenv
JarvisVenv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment
```powershell
copy .env.example .env
```
Edit `.env` and fill in your credentials (see Uber section below).

### 3. Configure the LLM
Edit `config/settings.py`:
```python
OLLAMA_HOST  = None              # None = localhost:11434
OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_STREAM = True
```

### 4. Run Jarvis
```powershell
JarvisVenv\Scripts\activate
python ollama_agent.py
```

---

## Uber MCP Integration

The Uber integration uses the open-source [199-mcp/mcp-uber](https://github.com/199-mcp/mcp-uber) server,
which communicates with the **Uber REST API via OAuth 2.0** (no browser automation).

### Uber Developer Dashboard Setup

1. Go to [https://developer.uber.com/dashboard](https://developer.uber.com/dashboard)
2. Open your app → **Auth** tab
3. Add redirect URI: `http://localhost:3000/callback`
4. Note your **Client ID** and **Client Secret**

### Environment variables (`.env`)
```
UBER_CLIENT_ID=<your client id>
UBER_CLIENT_SECRET=<your client secret>
UBER_REDIRECT_URI=http://localhost:3000/callback
UBER_ENVIRONMENT=sandbox
```
**Never commit `.env` to Git.** It is listed in `.gitignore`.

### Available Uber MCP tools

| Tool | Description | Auth required |
|---|---|---|
| `uber_get_auth_url` | Generate OAuth authorization URL | No |
| `uber_set_access_token` | Store user access token in MCP session | No |
| `uber_get_price_estimates` | Get fare estimates (requires lat/lng) | Yes |
| `uber_request_ride` | Request a ride (protected by confirmation gate) | Yes |
| `uber_get_ride_status` | Get ride status by request ID | Yes |
| `uber_cancel_ride` | Cancel an active ride | Yes |

### OAuth Flow

The first time you want to use Uber through Jarvis, you must authenticate:

**Terminal 1 — start Jarvis:**
```powershell
python ollama_agent.py
```

**Terminal 2 — start the OAuth callback helper:**
```powershell
node oauth_callback_server.js
```
> Requires: `npm install dotenv` in the project root (one-time setup).

**In Jarvis, say:**
```
Get an Uber auth URL for user jarvis
```
Jarvis calls `uber_get_auth_url` and returns a URL. Open it in your browser, authorize the app, and Uber will redirect to `http://localhost:3000/callback`. The callback server exchanges the code and **displays your access token** on screen.

**Back in Jarvis, say:**
```
Set my Uber access token to <paste token here> for user jarvis
```
Jarvis calls `uber_set_access_token`. You are now authenticated.

> **Note:** The token is held in memory by the MCP server process. If you restart Jarvis, you will need to authenticate again.

### Getting Price Estimates

The Uber MCP requires **numeric coordinates** (latitude/longitude), not place names.

Example:
```
Get an Uber price estimate for user jarvis from 12.8406, 80.1534 to 12.9941, 80.1709
```

| Location | Latitude | Longitude |
|---|---|---|
| VIT Chennai | 12.8406 | 80.1534 |
| Chennai International Airport | 12.9941 | 80.1709 |
| Chennai Central Station | 13.0827 | 80.2707 |
| T Nagar | 13.0418 | 80.2341 |

> Geocoding (converting place names to coordinates) is not implemented in this milestone.

### Booking Safety

`uber_request_ride` is protected by a hard confirmation gate in `ollama_agent.py`.
Regardless of what the LLM decides, the Python application will pause and require
you to type `YES` (all caps) before the tool call is dispatched. No automatic booking
is possible.

### Sandbox Mode

`UBER_ENVIRONMENT=sandbox` is the default. In sandbox mode:
- OAuth and authentication work exactly as in production.
- `uber_get_price_estimates` may return empty results for some coordinate pairs.
- `uber_request_ride` requires the `request` scope, which may need Uber approval.
- **Do not switch to `production` until Uber grants production access.**

---

## Adding More MCP Servers

Add a new entry to `MCP_SERVERS` in `config/settings.py`:
```python
"filesystem": {
    "command": "npx.cmd",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", str(BASE_DIR)],
    "env": {**os.environ},
},
```
Jarvis discovers all tools at startup and namespaces them as `<server>__<tool>`.

---

## Known Limitations

1. **Coordinates required** — `uber_get_price_estimates` needs raw lat/lng values. Geocoding from place names is not yet implemented.
2. **In-memory token** — The OAuth access token is lost when the MCP server restarts.
3. **`request` scope** — `uber_request_ride` may require Uber production approval before it works.
4. **Sandbox results** — Price estimates may be empty or synthetic in sandbox mode.
5. **OAuth helper process** — The `oauth_callback_server.js` must be running on port 3000 during authentication.

---

## License
MIT License
