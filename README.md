# Jarvis

A modular, multi-agent personal AI assistant powered by **Model Context Protocol (MCP)**, featuring dynamic tool orchestration, a robust Tool Registry, and flexible LLM provider support.

## Overview

Jarvis leverages a capability-based multi-agent architecture (Router -> Orchestrator -> Worker) to securely and intelligently execute tasks using various MCP servers. By abstracting the LLM provider and introducing a centralized Tool Registry, Jarvis can dynamically scale to hundreds of tools without overwhelming the language models.

## Core Architecture

`mermaid
flowchart TB
  U[User request] --> API[Starlette server]
  API --> R[Router Agent]
  R --> O[Orchestrator]
  
  subgraph ToolSystem [Tool System]
      TR[Tool Registry]
      TS[Tool Snapshot]
  end
  
  O -->|Request Capabilities| TR
  TR -->|Enabled Tools| TS
  TS --> W[Worker Agent]
  W --> P[LLM Provider]
  P --> MCP[MCP Clients]
  MCP --> W
  W --> API
  API --> UI[Browser UI via SSE]
  
  R -. failure .-> F[Single-agent fallback]
  F --> MCP
`

### The Multi-Agent Pipeline

1. **Router**: Analyzes the user's request. Answers simple questions directly, or delegates complex tasks (requiring tools, memory, or web search) to the Orchestrator, specifying the exact capabilities required.
2. **Tool Registry**: The single source of truth for all discovered MCP tools. It tracks tool metadata, server origins, capability buckets, and enabled/disabled states.
3. **Orchestrator**: Queries the Tool Registry for the requested capabilities, generating an immutable **Tool Snapshot** of eligible, enabled tools.
4. **Worker**: Executes the delegated task using strictly the tools provided in the Tool Snapshot. 

### Supported LLM Providers

Jarvis abstracts provider formatting, allowing you to seamlessly mix and match models for different agents (e.g., Gemini for the Router, Ollama for the Worker).
* **Ollama** (Default, local & safe)
* **Gemini** (Fully supported with recursive tool schema handling)
* **Anthropic** 
* **OpenAI** 

## Built-in Capabilities & MCP Servers

Jarvis maps high-level capabilities to specific MCP servers. 

| Capability | MCP Servers | Description |
| --- | --- | --- |
| web_research | Exa, Tavily, Firecrawl | Search the web and scrape content. |
| rowser_automation | Playwright | Automate browser interactions. |
| messaging | WhatsApp | Read and send WhatsApp messages. |
| ilesystem | Filesystem | Read, write, and manipulate local files. |
| memory | Memory | Read and write to Jarvis's long-term knowledge graph. |
| 	erminal | Terminal | Execute shell commands. |

## Recent Upgrades

### The Tool Registry (TR-1 to TR-4)
Jarvis now features a highly resilient **Tool Registry**:
* **Decoupled Architecture:** The MCP Client handles execution, while the Registry exclusively handles tool eligibility and cataloging.
* **Tool Snapshots:** Workers are initialized with isolated ToolSnapshot instances, guaranteeing they only receive explicitly enabled tools.
* **Provider Hardening:** Deep schema normalization (like injecting missing items in arrays for Gemini) happens at the adapter layer, keeping the registry provider-agnostic.
* **Stable Lifecycles:** Safe cross-agent client sharing prevents connection drops during Router -> Worker handoffs.

## Setup & Configuration

### 1. Installation
Install dependencies via uv:
\\\ash
uv pip install -e ".[dev]"
\\\

### 2. Environment Variables
Copy .env.example to .env and configure your LLM providers:
\\\env
# LLM Providers
JARVIS_ROUTER_PROVIDER=gemini
JARVIS_WORKER_PROVIDER=ollama
GEMINI_API_KEY=your_api_key_here

# MCP Servers
WHATSAPP_MCP_TRANSPORT=stdio
\\\

### 3. Usage & Bookkeeping
Jarvis includes a built-in Usage dashboard to monitor API quotas, token consumption, and model invocations across the Router and Worker pipelines. This is automatically tracked via the bookkeeping service.

## Development & Testing

Run the local server:
\\\ash
uv run main.py
\\\

To test integration layers (like the TR-4 Gemini provider fixes):
\\\ash
uv run python scratch/test_gemini_integration.py
uv run python scratch/test_tr3.py
\\\

## License
MIT License
