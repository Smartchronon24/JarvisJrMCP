"""
Jarvis Multi-Agent Architecture
===============================
Implements the Router → Orchestrator → Worker layer around the existing Jarvis ecosystem.

Hard Task Enforcement:
  Hard 1: Worker receives only resolved tools — enforced at Orchestrator level (ollama_agent.py)
  Hard 2: Disabled MCP enforcement — resolved_servers intersected with enabled_mcps
  Hard 3: Router hallucination protection — validate_decision() sanitises the Router's output
  Hard 4: Fallback — ROUTER_FAILED sentinel triggers single-agent execution in Orchestrator
  Hard 5: Multi-tool execution — allowed_tools can span multiple MCPs for a single capability
"""

import json
import logging
from config.settings import ROUTER_MODEL, WORKER_MODEL
import ollama

# Configure simple logging
logger = logging.getLogger("jarvis.multi_agent")

# ---------------------------------------------------------------------------
# Capability Registry (Easy 4)
# ---------------------------------------------------------------------------
# Maps high-level capability names → MCP server keys (as defined in settings.py)
CAPABILITY_REGISTRY = {
    "web_research": {
        "description": "Searching the web, extracting factual content from pages, and crawled summaries.",
        "mcps": ["exa", "tavily", "firecrawl"]
    },
    "browser_automation": {
        "description": "Controlling the web browser, interacting with web UI (clicking, typing, logging in).",
        "mcps": ["playwright"]
    },
    "messaging": {
        "description": "Reading and sending WhatsApp chats, searching WhatsApp contacts.",
        "mcps": ["whatsapp"]
    },
    "ride_booking": {
        "description": "Retrieving Uber ride estimates, requesting rides, checking ride status.",
        "mcps": ["uber"]
    },
    "filesystem": {
        "description": "Reading, writing, listing, and inspecting files on the local filesystem.",
        "mcps": ["filesystem"]
    },
    "memory": {
        "description": "Retrieving past facts, saving entities, logging user observations.",
        "mcps": ["memory"]
    }
}

# ---------------------------------------------------------------------------
# Sentinel — Hard 4 (Fallback)
# ---------------------------------------------------------------------------
# Returned by Router.route() when it fails entirely. The Orchestrator detects
# this and falls back to the original single-agent execution path.
ROUTER_FAILED = {"_router_failed": True}

# Required fields in a valid router decision
_REQUIRED_FIELDS = {"task_type", "capabilities", "worker_instruction", "reason"}

# ---------------------------------------------------------------------------
# Hard 3: Decision Validator
# ---------------------------------------------------------------------------

def validate_decision(decision: dict) -> dict:
    """
    Sanitise and validate a Router decision before the Orchestrator uses it.

    Rules enforced:
    1. If not a dict, reject entirely → return ROUTER_FAILED.
    2. Fill in any missing required fields with safe defaults.
    3. Strip unknown capability names (not in CAPABILITY_REGISTRY).
    4. Strip unknown MCP names in capability lists — not needed here because
       we only use capability names; MCPs come from CAPABILITY_REGISTRY.
    5. Log any corrections made for observability.

    Returns a clean, safe decision dict, or ROUTER_FAILED if it is irrecoverable.
    """
    if not isinstance(decision, dict):
        logger.warning("Router returned non-dict — falling back.")
        return ROUTER_FAILED

    # Don't mutate the original
    d = dict(decision)
    corrections = []

    # --- Fill missing required fields ---
    if "task_type" not in d or not isinstance(d.get("task_type"), str):
        d["task_type"] = "general_chat"
        corrections.append("task_type defaulted to 'general_chat'")

    if "capabilities" not in d or not isinstance(d.get("capabilities"), list):
        d["capabilities"] = []
        corrections.append("capabilities defaulted to []")

    if "worker_instruction" not in d or not isinstance(d.get("worker_instruction"), str):
        d["worker_instruction"] = ""
        corrections.append("worker_instruction defaulted to ''")

    if "reason" not in d or not isinstance(d.get("reason"), str):
        d["reason"] = "(no reason provided)"
        corrections.append("reason defaulted")

    # --- Strip unknown capability names (Hard 3) ---
    unknown_caps = [c for c in d["capabilities"] if c not in CAPABILITY_REGISTRY]
    if unknown_caps:
        d["capabilities"] = [c for c in d["capabilities"] if c in CAPABILITY_REGISTRY]
        corrections.append(f"stripped unknown capabilities: {unknown_caps}")

    if corrections:
        logger.warning(f"Router decision repaired — corrections: {corrections}")

    logger.info(f"Validated Router decision: {json.dumps(d, indent=2)}")
    return d


# ---------------------------------------------------------------------------
# Router (Easy 2)
# ---------------------------------------------------------------------------

class Router:
    def __init__(self, model: str = ROUTER_MODEL):
        self.model = model

    def _build_system_prompt(self) -> str:
        capabilities_desc = ""
        for cap, info in CAPABILITY_REGISTRY.items():
            capabilities_desc += f"- {cap}: {info['description']} (MCP servers: {', '.join(info['mcps'])})\n"

        prompt = f"""You are the Router for Jarvis, a personal AI assistant.
Your job is to analyze the user's message and determine the task type, the required capabilities, and build a concise instruction for the Worker.

Available Capabilities:
{capabilities_desc}

You MUST return a JSON object with the following fields:
- task_type: A short string identifying the task category (e.g., "web_research", "browser_task", "messaging_task", "ride_booking", "filesystem_task", "memory_task", or "general_chat").
- capabilities: A JSON array of capability names from the list above only. Can be empty [] if no specialist tool is needed (e.g. for simple chat).
- worker_instruction: A clear, actionable directive for the Worker LLM to execute. Do not include your internal planning.
- reason: A brief explanation of why you chose these capabilities.

STRICT RULES:
- Only use capability names exactly as listed above. Do not invent new capability names.
- If the user is asking a simple conversational question (no tools needed), return an empty capabilities array.
- Do not output any markdown code blocks, explanations, or text outside the JSON object. Return ONLY valid JSON.

Example output:
{{
  "task_type": "web_research",
  "capabilities": ["web_research"],
  "worker_instruction": "Compare current RTX 5070 listings in India and identify the best options.",
  "reason": "The user is asking for current external web information."
}}
"""
        return prompt

    async def route(self, user_message: str, context: list[dict]) -> dict:
        """
        Analyze user message and context to produce a structured routing decision.

        Returns ROUTER_FAILED (Hard 4 sentinel) if the Router model is unavailable,
        times out, or returns unrecoverable output. The Orchestrator handles the fallback.
        """
        messages = [
            {"role": "system", "content": self._build_system_prompt()}
        ]

        # Add a slice of recent conversation context (last 6 turns)
        for msg in context[-6:]:
            if msg["role"] in ("user", "assistant") and msg.get("content"):
                messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": user_message})

        logger.info(f"Routing request with model '{self.model}'...")

        try:
            # format="json" instructs Ollama to guarantee a JSON response
            response = ollama.chat(
                model=self.model,
                messages=messages,
                format="json"
            )
            raw_content = response.message.content or ""
            raw_content = raw_content.strip()

            if not raw_content:
                logger.warning("Router returned empty content — falling back.")
                return ROUTER_FAILED

            decision = json.loads(raw_content)
            # Hard 3: validate and sanitise before returning
            return validate_decision(decision)

        except json.JSONDecodeError as e:
            logger.error(f"Router returned invalid JSON: {e}")
            return ROUTER_FAILED

        except Exception as e:
            # Hard 4: Model unavailable, network error, timeout, etc.
            logger.error(f"Router failed with exception: {e}")
            return ROUTER_FAILED


# ---------------------------------------------------------------------------
# Worker (Easy 5)
# ---------------------------------------------------------------------------

class Worker:
    def __init__(self, model: str = WORKER_MODEL, tools: list[dict] = None):
        self.model = model
        # tools is the RESTRICTED set of Ollama-format tool defs passed by the Orchestrator
        self.tools = tools or []
        # Build a fast lookup set of allowed scoped tool names (Hard 1 enforcement helper)
        self.allowed_tool_names: set[str] = {
            t["function"]["name"] for t in self.tools
        }

    def build_system_prompt(self, router_instruction: str) -> str:
        """Build a focused system prompt scoped to the Router's instruction."""
        tool_list = "\n".join(f"  - {n}" for n in sorted(self.allowed_tool_names)) or "  (none)"
        prompt = f"""You are a Jarvis Worker agent. Your sole purpose is to complete the following specific instruction.

Specific Task:
"{router_instruction}"

Guidelines:
- You have access ONLY to the tools listed below. Do not attempt to call any tool not on this list.
- If the task cannot be completed with the available tools, say so clearly.
- Keep your final output concise and directly address the user's objective.

Your available tools:
{tool_list}
"""
        return prompt
