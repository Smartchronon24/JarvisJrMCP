# Jarvis Web UI

This directory contains the responsive browser dashboard for Jarvis. It owns chat presentation, streaming updates, activity visibility, MCP settings, and the tools view. Backend routing and policy decisions remain in the Python application.

---

## UI flow

The browser sends a message to the local streaming endpoint and renders each event as it arrives.

```
┌─────────────────────────────────┐
│       Browser (Frontend)        │
│  (chat.js, settings.js, etc.)   │
└────────────────┬────────────────┘
                 │
                 │ 1. POST /api/chat/stream {message}
                 │ 2. Read SSE Chunk Stream
                 ▼
┌─────────────────────────────────┐
│    Starlette Server (Backend)   │
│        (app/server.py)          │
└────────────────┬────────────────┘
                 │
                 │ 3. Call async generator (agent.chat_stream)
                 ▼
┌─────────────────────────────────┐
│      Jarvis Python backend      │
│ Router → Orchestrator → Worker │
└─────────────────────────────────┘
```

---

## ⚡ Server-Sent Events (SSE) Schema

Streaming is served via `POST /api/chat/stream`. The response is a line-delimited stream of JSON event frames prefixed with `data:`.

The `agent` field identifies the source of visible activity: `router`, `worker`, or `jarvis` for the fallback/general stream.

### Event Definitions

#### 1. `request_start`
Emitted immediately when a chat request begins.
```json
{ "type": "request_start", "agent": "jarvis" }
```

#### 2. `assistant_start`
Emitted when the LLM starts generating text tokens.
```json
{ "type": "assistant_start", "agent": "jarvis" }
```

#### 3. `assistant_delta`
Emitted for every incremental text token.
```json
{ "type": "assistant_delta", "agent": "jarvis", "content": "Hello" }
```

#### 4. `tool_call_start`
Emitted before executing an MCP tool. Used to display a *Running* status.
```json
{
  "type": "tool_call_start",
  "agent": "jarvis",
  "id": "exec-140685718290320",
  "server": "tavily",
  "tool": "search",
  "arguments": { "query": "RTX 5090 specs" }
}
```

#### 5. `tool_call_result`
Emitted upon successful execution of an MCP tool.
```json
{
  "type": "tool_call_result",
  "agent": "jarvis",
  "id": "exec-140685718290320",
  "server": "tavily",
  "tool": "search",
  "result": "{ \"results\": [...] }"
}
```

#### 5a. `plan_created`
Emitted when the Worker creates a concise multi-step execution plan. The
steps are display-safe summaries and are rendered in the Activity pane. This
event does not represent private chain-of-thought or trigger another LLM call.
```json
{
  "type": "plan_created",
  "agent": "worker",
  "id": "worker_plan_1",
  "steps": [
    "Find relevant candidates",
    "Compare candidates",
    "Verify important details"
  ]
}
```

#### 6. `tool_call_error`
Emitted if an MCP tool throws an exception during execution.
```json
{
  "type": "tool_call_error",
  "agent": "jarvis",
  "id": "exec-140685718290320",
  "server": "tavily",
  "tool": "search",
  "error": "API Key Invalid"
}
```

#### 7. `assistant_complete`
Emitted when the current LLM turn is completed.
```json
{ "type": "assistant_complete", "agent": "jarvis" }
```

#### 8. `request_complete`
Emitted when the entire agentic loop finishes.
```json
{ "type": "request_complete", "agent": "jarvis", "cancelled": false }
```

#### 9. `request_error`
Emitted on fatal/unexpected core errors.
```json
{ "type": "request_error", "agent": "jarvis", "error": "Ollama connection lost" }
```

---

## MCP settings UI

1. The user clicks a switch on the Settings page.
2. The switch updates optimistically.
3. `settings.js` sends a `POST /api/settings/mcp` payload:
   ```json
   { "server_name": "tavily", "enabled": false }
   ```
4. On success, the UI keeps the new state and refreshes the connected-server/tool views as needed.
5. On failure, the UI restores the original switch state and reports the error.

---

## Stop generation

The UI supports stopping long-running agent responses in real time.

1. While a stream is active, the Send button changes to Stop.
2. Clicking Stop sends `POST /api/chat/cancel`.
3. The UI continues to display the partial assistant response.
4. `request_complete` resets the streaming state and restores the normal Send button.

---

## Frontend components

* **`state.js` (`AppState`)**: Centralizes messages, tool executions, MCP status, and streaming state; publishes UI events.
* **`chat.js` (`ChatInterface`)**: Sends messages, parses SSE frames, appends assistant deltas, and maps Router/Worker/tool events into application state.
* **`activity.js` (`ActivityScreen`)**: Displays live execution cards with source, tool, arguments, result, status, and duration.
* **Worker plan cards**: `plan_created` events are stored by `state.js` and rendered by `activity.js` alongside tool execution cards.
* **`settings.js` (`SettingsScreen`)**: Renders MCP switches and synchronizes their state with the settings API, including optimistic updates and rollback.
* **`tools.js` (`ToolsScreen`)**: Lists the tools reported by connected MCP servers.
* **`theme.js` and `events.js`**: Manage theme preferences and shared browser events.

## Run the UI

Start the Python server from the project root:

```bash
python main.py
```

Then open `http://127.0.0.1:8000`. The frontend is served from `src/` by the Starlette server; it is not a separate build step.