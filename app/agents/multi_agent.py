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
import re
import time
from config.settings import ROUTER_MODEL, WORKER_MODEL
import ollama

# Configure simple logging
logger = logging.getLogger("jarvis.multi_agent")

_CAPABILITY_INTENT_PATTERNS = {
    "memory": re.compile(r"\b(?:memory|remember|recollect|recall|forget|forgot|stored|save|saved)\b", re.IGNORECASE),
    "web_research": re.compile(r"\b(?:search|research|latest|current|recent|news|price|prices)\b", re.IGNORECASE),
    "browser_automation": re.compile(r"\b(?:open|navigate|click|type|fill|browse|website|webpage)\b", re.IGNORECASE),
    "messaging": re.compile(r"\b(?:whatsapp|message|contact|send)\b", re.IGNORECASE),
    "filesystem": re.compile(r"\b(?:file|folder|directory|read|write|list)\b", re.IGNORECASE),
}

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

    if d.get("action") not in ("respond", "delegate"):
        d["action"] = "delegate"
        corrections.append("action defaulted to 'delegate'")

    if d["action"] == "respond" and not isinstance(d.get("response"), str):
        d["action"] = "delegate"
        corrections.append("invalid direct response changed to 'delegate'")

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

    if d["action"] == "respond":
        d["capabilities"] = []
        d["worker_instruction"] = ""

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
Your job is to either answer a simple request directly or delegate it to the Worker.

Available Capabilities:
{capabilities_desc}

You MUST return a JSON object with the following fields:
- action: Either "respond" for a simple request you can answer reliably without tools, current information, or external actions, or "delegate" for everything else.
- response: The complete answer when action is "respond". Use an empty string when action is "delegate".
- task_type: A short string identifying the task category (e.g., "web_research", "browser_task", "messaging_task", "filesystem_task", "memory_task", or "general_chat").
- capabilities: A JSON array of capability names from the list above only. Can be empty [] if no specialist tool is needed (e.g. for simple chat).
- worker_instruction: A clear, actionable directive for the Worker LLM to execute. Do not include your internal planning.
- reason: A brief explanation of why you chose these capabilities.

STRICT RULES:
- Only use capability names exactly as listed above. Do not invent new capability names.
- Use action "respond" only for greetings, casual conversation, simple factual questions, basic explanations, and other requests comfortably within your capabilities.
- Use action "delegate" if the request needs any MCP tool, external action, web search, current or time-sensitive information, specialized or deep reasoning, multi-step execution, or if you are uncertain.
- Any request involving Jarvis memory, including "remember me", "recollect your memory", "use your memory", recalling stored facts, or saving information, MUST use action "delegate" with capability "memory". Do not answer these from general knowledge or claim that memory is unavailable.
- Requests involving WhatsApp, files, websites, messages, rides, or searching MUST also use action "delegate" with the matching capability.
- Never answer a request for latest, current, recent, live, or externally verified information from model knowledge. Delegate it.
- For action "respond", set capabilities to [], worker_instruction to "", and put only the user-facing answer in response.
- For action "delegate", set response to "" and provide the required capability names and worker_instruction.
- Do not output any markdown code blocks, explanations, or text outside the JSON object. Return ONLY valid JSON.

Example output:
{{
    "action": "delegate",
    "response": "",
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
            t0 = time.time()
            response = ollama.chat(
                model=self.model,
                messages=messages,
                format="json"
            )
            duration_ms = int((time.time() - t0) * 1000)

            # Extract token counts if exposed by Ollama
            p_tokens = getattr(response, "prompt_eval_count", None)
            c_tokens = getattr(response, "eval_count", None)
            t_tokens = (p_tokens + c_tokens) if (p_tokens is not None and c_tokens is not None) else None

            from app.bookkeeping.service import bookkeeping_service
            bookkeeping_service.record_llm_usage(
                model=self.model,
                role="router",
                success=True,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                total_tokens=t_tokens,
                duration_ms=duration_ms,
            )

            raw_content = response.message.content or ""
            raw_content = raw_content.strip()

            if not raw_content:
                logger.warning("Router returned empty content — falling back.")
                return ROUTER_FAILED

            decision = json.loads(raw_content)
            # Hard 3: validate and sanitise before returning
            decision = validate_decision(decision)
            return self._enforce_capability_intent(decision, user_message)

        except json.JSONDecodeError as e:
            logger.error(f"Router returned invalid JSON: {e}")
            from app.bookkeeping.service import bookkeeping_service
            bookkeeping_service.record_llm_usage(
                model=self.model,
                role="router",
                success=False,
                error_info=f"JSONDecodeError: {e}"
            )
            return ROUTER_FAILED

        except Exception as e:
            # Hard 4: Model unavailable, network error, timeout, etc.
            logger.error(f"Router failed with exception: {e}")
            from app.bookkeeping.service import bookkeeping_service
            bookkeeping_service.record_llm_usage(
                model=self.model,
                role="router",
                success=False,
                error_info=str(e)
            )
            return ROUTER_FAILED

    @staticmethod
    def _enforce_capability_intent(decision: dict, user_message: str) -> dict:
        """Prevent an overconfident direct answer from bypassing an obvious MCP request."""
        if decision.get("action") != "respond":
            return decision

        for capability, pattern in _CAPABILITY_INTENT_PATTERNS.items():
            if pattern.search(user_message):
                return {
                    **decision,
                    "action": "delegate",
                    "response": "",
                    "task_type": f"{capability}_task",
                    "capabilities": [capability],
                    "worker_instruction": user_message,
                    "reason": f"The request matches the {capability} capability and must be handled with its MCP tools.",
                }

        return decision


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
- Decide whether the task is simple enough to complete directly. Do not create a plan for a single-step task.
- For a genuinely multi-step task, form a concise working plan before acting. Keep only the necessary steps and use it to track what remains.
- When you create a multi-step plan, expose only its concise user-visible steps once, before acting, using exactly this format (omit it for single-step tasks):
    <jarvis_plan>
    1. First step
    2. Second step
    </jarvis_plan>
- Execute the plan incrementally with the available tools. After each tool result, assess what it establishes, mark the relevant step complete, and adapt the remaining steps when results are missing, contradictory, or unexpected.
- Treat tool results as evidence for subsequent steps. Do not claim a step or the overall task is complete unless the available results support it.
- Do not reveal private chain-of-thought. If useful, communicate only a brief user-facing summary of the current step or plan.

Your available tools:
{tool_list}
"""
        return prompt

    @staticmethod
    def extract_plan(content: str) -> tuple[str, list[str]]:
        """Extract the Worker's concise display plan without exposing the marker in chat."""
        match = re.search(r"<jarvis_plan>\s*(.*?)\s*</jarvis_plan>", content, re.DOTALL | re.IGNORECASE)
        if not match:
            return content, []

        steps = []
        for line in match.group(1).splitlines():
            step = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
            if step:
                steps.append(step)
        clean_content = (content[:match.start()] + content[match.end():]).strip()
        return clean_content, steps
