# JarvisMCP

A minimal yet powerful **Model Context Protocol (MCP)** based AI assistant built on Ollama. Jarvis can remember facts, interact with external services, browse the web, and chat using large language models — all through a clean plugin-style MCP architecture.

---

## ✨ Features
- **Memory MCP** — Persistent graph-based store for entities, observations, and relations. Data is saved under `data/MemoryMCP/memory.jsonl`.
- **Uber MCP** — OAuth 2.0 + Uber REST API integration. Get price estimates, check ride status.
- **Filesystem MCP** — Integrates official `@modelcontextprotocol/server-filesystem` mapped specifically to the sandbox directory `data/FilesystemMCP/`.
- **Playwright MCP** — Microsoft's official `@playwright/mcp` browser automation server. Headed Chromium browser launches by default to let you observe interactions. Ephemeral snapshots, screenshots, and logs are isolated inside `data/PlaywrightMCP/`.
- **OAuth Callback Server** — A standalone helper script (`oauth_callback_server.js`) to capture the authorization redirect on port 3000 and display the token.
- **Booking Safety Guard** — Intercepts `uber_request_ride` and demands explicit terminal confirmation (`YES`) before executing the ride request.
- **Tool-first architecture** — The LLM follows the exact JSON schema of each MCP tool.
- **Configurable endpoint** — Run against local Ollama or a remote corporate server.
- **Streaming / non-streaming** output mode.
- **Graceful fallback** when a model does not support tools.

---

## 📁 Repository layout
```
JarvisMCP/
├─ config/
│   └─ settings.py            # Host, model, MCP server map, system prompt
├─ ollama_agent.py             # Main entry point, chat loop, tool dispatch & safety gate
├─ oauth_callback_server.js    # Uber OAuth callback helper (run separately during auth)
├─ .env.example                # Environment variable template (no real credentials)
├─ data/                       # Configured local data workspace directory
│   ├─ MemoryMCP/              # Confinement folder for Memory server database
│   ├─ FilesystemMCP/          # Sandbox directory for Filesystem server operations
│   └─ PlaywrightMCP/          # Sandbox folder for Playwright server logs and snapshots
├─ .gitignore
└─ README.md
```

---

## ⚙️ Quick Start

### Prerequisites
| Requirement | Version |
|---|---|
| Python | 3.12+ |
| Node.js / npm | 18+ (for npx MCP servers) |
| Ollama | Any recent version |

### 1. Install dependencies
Activate your virtual environment and install requirements:
```powershell
python -m venv JarvisVenv
JarvisVenv\Scripts\activate
pip install -r requirements.txt
npm install dotenv
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
OLLAMA_MODEL = "gpt-oss:120b-cloud"
OLLAMA_STREAM = True
```

### 4. Run Jarvis
```powershell
JarvisVenv\Scripts\activate
python ollama_agent.py
```
You’ll see a banner listing all dynamically connected MCP servers and their discovered tools.

---

## 🚗 Uber MCP OAuth Flow

The Uber integration uses the open-source [199-mcp/mcp-uber](https://github.com/199-mcp/mcp-uber) server, which communicates with the **Uber REST API via OAuth 2.0** (no browser automation).

### Uber Developer Dashboard Setup
1. Go to [https://developer.uber.com/dashboard](https://developer.uber.com/dashboard).
2. Open your app → **Auth** tab.
3. Add redirect URI: `http://localhost:3000/callback`
4. Note your **Client ID** and **Client Secret**.

### Environment variables (`.env`)
```
UBER_CLIENT_ID=<your client id>
UBER_CLIENT_SECRET=<your client secret>
UBER_REDIRECT_URI=http://localhost:3000/callback
UBER_ENVIRONMENT=sandbox
```
**Never commit `.env` to Git.** It is listed in `.gitignore`.

### OAuth Verification Flow
1. **Start Jarvis** in Terminal 1:
   ```powershell
   python ollama_agent.py
   ```
2. **Start the Callback Helper** in Terminal 2:
   ```powershell
   node oauth_callback_server.js
   ```
3. **Generate URL:** In Jarvis, type:
   ```
   Get an Uber auth URL for user jarvis
   ```
4. **Authorize:** Open the generated URL in your browser, log in, and authorize the application.
5. **Set Token:** Copy the access token displayed on `localhost:3000/callback` and provide it to Jarvis:
   ```
   Set my Uber access token to <paste token here> for user jarvis
   ```

> [!WARNING]
> **Invalid Scope Error:** If your app's review is pending on the Uber Developer Dashboard, requesting the privileged scopes `request` and `ride_request` will return an `invalid_scope` error. For testing OAuth, you may need to restrict the requested scopes to `profile` only in the MCP server setup.

---

## 🌐 Playwright MCP Web Browsing

Playwright tool interaction relies on **ephemeral session references (`ref`)** generated dynamically per snapshot (e.g. `[ref=e8]` for a button).

To command browser tasks:
1. **Navigate:** Ask Jarvis to open a page: `Open https://demo.playwright.dev/todomvc`
2. **Inspect:** Take a snapshot to see the elements: `Take a snapshot of the page`
3. **Interact:** Click or type by specifying the reference ID shown in the snapshot hierarchy: `Click the textbox with reference e8`

---

## 🛠️ Sandbox & Confinement

To keep your workspace clean and secure, local modifications and outputs are restricted:
- **Filesystem MCP:** Operations are confined strictly within the project-controlled `data/FilesystemMCP/` folder. Directory traversal attempts outside this folder are denied.
- **Playwright MCP:** Captured accessibility snapshots, console logs, and browser screenshots are isolated inside the `data/PlaywrightMCP/` directory.

---

## Known Limitations

1. **Coordinates required** — `uber_get_price_estimates` needs raw lat/lng values. Geocoding from place names is not yet implemented.
2. **In-memory token** — The OAuth access token is lost when the MCP server restarts.
3. **Headed browser** — The Playwright browser opens visually by default for testing.
4. **OAuth helper process** — The `oauth_callback_server.js` must be running on port 3000 during authentication.

---

## License
MIT License
