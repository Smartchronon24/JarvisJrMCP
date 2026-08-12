# JarvisMCP

A minimal yet powerful **Model Context Protocol (MCP)** based AI assistant built on Ollama. Jarvis can remember facts, reason with tools, and chat using large language models.

---

## ✨ Features
- **Memory MCP**: Persistent graph‑based store for entities, observations, and relations.
- **Tool‑first architecture**: The LLM is forced to follow the exact JSON schema of each tool. No fragile regex‑based fixes.
- **Configurable endpoint**: Run against a local Ollama server **or** a remote corporate Ollama instance.
- **Streaming / non‑streaming** output mode.
- **Graceful fallback** when a model does not support tools (e.g., vision models).
- **Extensible**: Add more MCP servers (filesystem, todo, etc.) by editing `config/settings.py`.

---

## 📁 Repository layout
```
JarvisMCP/
├─ config/                # Settings & constants
│   └─ settings.py        # Host, model, stream flag, MCP server map
├─ ollama_agent.py        # Main entry point, chat loop, tool dispatch
├─ data/                  # Memory database (JSONL) – generated at runtime
├─ .gitignore
└─ README.md              # (this file)
```

---

## ⚙️ Quick start
### 1️⃣ Prerequisites
- **Python 3.11+** (virtual environment recommended)
- **Ollama** installed and running (`ollama serve`).
- Desired model pulled via `ollama pull <model>`.

### 2️⃣ Install dependencies
```powershell
# From the project root
python -m venv JarvisVenv
JarvisVenv\Scripts\activate
pip install -r requirements.txt   # contains `ollama` SDK
```

### 3️⃣ Configure
Edit `config/settings.py`:
```python
# Local (default) – uses http://localhost:11434
OLLAMA_HOST = None
OLLAMA_MODEL = "llama3.1:8b"

# Remote corporate server – uncomment to use
# OLLAMA_HOST = "http://10.1.1.105:31434"
# OLLAMA_MODEL = "gpt-oss:120b-cloud"

OLLAMA_STREAM = True   # False = wait for full response
```
*Setting `OLLAMA_HOST = None` falls back to the local default.*

### 4️⃣ Run the assistant
```powershell
python ollama_agent.py
```
You’ll see a banner with the selected model and endpoint. Type messages at the `Jarvis>` prompt. Use `exit` or `quit` to stop.

---

## 🔧 Advanced usage
### Switching streaming mode
- **Streaming** (`OLLAMA_STREAM = True`): prints token‑by‑token as they arrive.
- **Non‑streaming** (`False`): waits for the whole response before printing.

### Handling models without tool support
Some models (e.g., `llama3.2‑vision`) reject the `tools` field. The client now automatically retries the request **without** tools and displays a notice, so plain chat still works.

### Adding more MCP servers
Add a new entry to `MCP_SERVERS` in `settings.py`:
```python
"filesystem": {
    "command": "npx.cmd",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", str(BASE_DIR)],
    "env": {**os.environ},
},
```
The agent will discover the server’s tools at startup and expose them under the `<server>__<tool>` namespace.

---

## 🛠️ Development notes
- **Tool schema enforcement**: `JarvisAgent.execute_tool` validates arguments against the `input_schema` coming from the MCP server. Invalid calls raise a clear error back to the LLM.
- **Endpoint flexibility**: The Ollama client is constructed as:
  ```python
  client = Client(host=OLLAMA_HOST) if OLLAMA_HOST else Client()
  ```
  This means `None` → default localhost, otherwise a full URL.
- **Future‑proof**: The architecture separates **MCP server management**, **LLM interaction**, and **application logic**, making it straightforward to plug in new servers or swap LLM back‑ends.

---

## 📜 License
This project is provided under the MIT License.

---

## 🙋‍♀️ Contributing
Feel free to open issues or pull requests. When adding new MCP servers, update the README’s "Adding more MCP servers" section.
