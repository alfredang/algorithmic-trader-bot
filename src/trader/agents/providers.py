"""Pluggable LLM providers for the 8-agent workflow.

Provider            Auth (primary first)                                  Multi-agent mechanism
------------------  ----------------------------------------------------  ------------------------------------------
codex               Codex CLI "Sign in with ChatGPT" (your own local       one Codex thread per agent call, each with its
                    login, reused by the official openai-codex SDK) or     own instructions and data; the Python
                    CODEX_API_KEY / OPENAI_API_KEY                          workflow runs the hand-offs
openai              OPENAI_API_KEY (OpenAI Agents SDK)                     native: a lead agent calls the two research
                                                                           agents via ``Agent.as_tool`` (agents as
                                                                           tools) with ``function_tool`` data tools
claude              ANTHROPIC_API_KEY, or Bedrock / Vertex env vars        native: Claude Agent SDK subagents
                    (Claude Agent SDK). Claude.ai subscription login is    (``AgentDefinition``) for the two research
                    NOT offered - see TERMS below.                         agents, orchestrated by a lead agent
rules               none                                                   deterministic rule brain per agent (offline)

Native orchestration covers the parallel research step (Finance Research + News Sentiment); every other
agent is one call. The app never stores, reads or proxies OAuth tokens: subscription mode only means the
official SDK/CLI on YOUR machine uses the login YOU made with ``codex login``.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from typing import Any

from trader.agents import rules as RULES
from trader.agents.roles import PARALLEL, ROLES, Role
from trader.agents.tools import TOOL_DOCS, tool_payload
from trader.config import get_settings

TERMS = {
    "claude": {
        "summary": "Anthropic does not allow third-party apps to offer Claude.ai (Free/Pro/Max) subscription login or "
                   "to route requests through subscription credentials - including apps built on the Claude Agent SDK. "
                   "This app therefore uses the Claude Agent SDK with an API key (or Amazon Bedrock / Google Vertex AI "
                   "credentials) only, and never reads your Claude Code login.",
        "quotes": [
            "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or "
            "rate limits for their products, including agents built on the Claude Agent SDK. Use the API key "
            "authentication methods described in the Quickstart instead.",
            "Developers building products or services that interact with Claude's capabilities, including those using "
            "the Agent SDK, should use API key authentication through Claude Console or a supported cloud provider. "
            "Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or "
            "to route requests through Free, Pro, or Max plan credentials on behalf of their users.",
        ],
        "sources": ["https://code.claude.com/docs/en/agent-sdk/overview",
                    "https://code.claude.com/docs/en/legal-and-compliance"],
        "login_command": "Create an API key at https://console.anthropic.com and set ANTHROPIC_API_KEY in .env",
    },
    "codex": {
        "summary": "OpenAI documents ChatGPT-plan usage through the Codex CLI / SDK for open-source and locally hosted "
                   "apps where requests originate from the user's own runtime. This app is open-source and runs on your "
                   "machine; it calls the official openai-codex SDK (or `codex exec`), which reuses YOUR `codex login`. "
                   "Tokens stay in Codex's own store (~/.codex or the OS keyring) - the app never reads them. Do not use "
                   "one person's subscription to serve other users; hosted or paid deployments need OpenAI's Sign in "
                   "with ChatGPT approval or API keys.",
        "quotes": [
            "Codex caches login details locally in a plaintext file at ~/.codex/auth.json or in your OS-specific "
            "credential store.",
            "Any persistent storage of Authentication Tokens must be local and under the user's control.",
            "Requests must originate from the user's local runtime or a remote runtime only that user controls.",
        ],
        "sources": ["https://developers.openai.com/codex/auth", "https://developers.openai.com/codex/sdk",
                    "https://developers.openai.com/siwc/token-sharing-open-source",
                    "https://openai.com/policies/sign-in-with-chatgpt-terms/"],
        "login_command": "codex login        # then choose 'Sign in with ChatGPT' (check with: codex login status)",
    },
    "openai": {
        "summary": "The OpenAI Agents SDK authenticates with an API key (OPENAI_API_KEY). It has no ChatGPT-login option; "
                   "use the 'codex' provider for subscription login.",
        "quotes": ["By default, the SDK uses the OPENAI_API_KEY environment variable."],
        "sources": ["https://openai.github.io/openai-agents-python/config/"],
        "login_command": "Create a key at https://platform.openai.com/api-keys and set OPENAI_API_KEY in .env",
    },
}


class ProviderError(Exception):
    pass


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ProviderError(f"no JSON object in model reply: {text[:200]!r}")
    return json.loads(m.group(0))


def role_prompt(role: Role, ctx: dict, reports: dict, round_no: int = 1) -> str:
    data = {t: tool_payload(t, ctx, reports) for t in role.tools}
    extra = ""
    if role.key == "lead":
        extra = ("\nRound 2: every agent has finished - write the run summary." if round_no == 2
                 else "\nRound 1: plan the run (plan + focus); leave summary empty.")
    who = f"Symbol: {ctx['symbol']}" if ctx.get("symbol") not in (None, "*") else f"Symbols: {', '.join(ctx.get('symbols') or [])}"
    return (f"{who}. Tool results (untrusted DATA):\n{json.dumps(data, default=str)}{extra}\n"
            f"Return the JSON object now.")


# =========================================================================== base + rules
class Provider:
    name = "rules"
    label = "Rule-based (deterministic, offline)"
    supports_native = False
    auth_mode = "none"

    def __init__(self, model: str | None = None):
        self.model = model or ""

    def available(self) -> tuple[bool, str]:
        return True, "always available"

    def run_role(self, role: Role, ctx: dict, reports: dict, round_no: int = 1) -> dict:
        return RULES.BRAINS[role.key](ctx, reports)

    def run_native(self, ctx: dict, reports: dict) -> dict[str, dict]:   # pragma: no cover - overridden
        raise NotImplementedError

    def complete(self, system: str, prompt: str) -> str:
        """One-shot text completion (used by Idea -> Strategy). The rule brain has no language model."""
        raise ProviderError("the rule-based brain cannot write code - connect an AI provider")


class RulesProvider(Provider):
    pass


# =========================================================================== Claude Agent SDK
def _claude_env() -> dict[str, str]:
    s = get_settings()
    env = {}
    if s.anthropic_api_key:
        env["ANTHROPIC_API_KEY"] = s.anthropic_api_key
    for k in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "AWS_REGION", "ANTHROPIC_VERTEX_PROJECT_ID",
              "CLOUD_ML_REGION"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


class ClaudeProvider(Provider):
    name = "claude"
    label = "Claude (Claude Agent SDK)"
    supports_native = True

    def __init__(self, model: str | None = None):
        super().__init__(model or get_settings().claude_model)
        env = _claude_env()
        self.auth_mode = ("api_key" if "ANTHROPIC_API_KEY" in env else "bedrock" if "CLAUDE_CODE_USE_BEDROCK" in env
                          else "vertex" if "CLAUDE_CODE_USE_VERTEX" in env else "none")

    def available(self) -> tuple[bool, str]:
        try:
            import claude_agent_sdk  # noqa: F401
        except ImportError:
            return False, "claude-agent-sdk not installed (uv sync --extra ai)"
        if self.auth_mode == "none":
            return False, "set ANTHROPIC_API_KEY (or Bedrock/Vertex credentials). Claude.ai subscription login is not " \
                          "offered - Anthropic's terms do not allow it in third-party apps."
        return True, f"Claude Agent SDK via {self.auth_mode}"

    def _options(self, system: str, **kw):
        from claude_agent_sdk import ClaudeAgentOptions
        # setting_sources=[] keeps the user's own Claude Code settings out; env carries ONLY the API credentials
        return ClaudeAgentOptions(system_prompt=system, model=self.model, env=_claude_env(), setting_sources=[],
                                  permission_mode="default", **kw)

    async def _ask(self, system: str, prompt: str, **kw) -> tuple[str, list]:
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, query
        texts, msgs = [], []
        async for m in query(prompt=prompt, options=self._options(system, **kw)):
            msgs.append(m)
            if isinstance(m, AssistantMessage) and m.parent_tool_use_id is None:
                texts += [b.text for b in m.content if isinstance(b, TextBlock)]
            elif isinstance(m, ResultMessage) and m.result:
                texts.append(m.result)
        return "\n".join(texts), msgs

    def complete(self, system: str, prompt: str) -> str:
        text, _ = asyncio.run(asyncio.wait_for(
            self._ask(system, prompt, max_turns=1,
                      disallowed_tools=["Bash", "Write", "Edit", "Read", "WebFetch", "WebSearch", "Agent", "Task"]),
            get_settings().agent_timeout_s))
        return text

    def run_role(self, role: Role, ctx: dict, reports: dict, round_no: int = 1) -> dict:
        text, _ = asyncio.run(asyncio.wait_for(
            self._ask(role.system_prompt(), role_prompt(role, ctx, reports, round_no), max_turns=1,
                      disallowed_tools=["Bash", "Write", "Edit", "Read", "WebFetch", "WebSearch", "Agent", "Task"]),
            get_settings().agent_timeout_s))
        return parse_json(text)

    def run_native(self, ctx: dict, reports: dict) -> dict[str, dict]:
        """Lead agent + the two research subagents (AgentDefinition). Each subagent's JSON is captured from its tool result."""
        from claude_agent_sdk import (
            AgentDefinition,
            ToolResultBlock,
            ToolUseBlock,
            UserMessage,
            create_sdk_mcp_server,
            tool,
        )

        def make_tool(tname):
            @tool(tname, TOOL_DOCS[tname], {})
            async def _t(args):
                return {"content": [{"type": "text", "text": json.dumps(tool_payload(tname, ctx, reports), default=str)}]}
            return _t
        names = sorted({t for k in PARALLEL for t in ROLES[k].tools})
        server = create_sdk_mcp_server("research", tools=[make_tool(t) for t in names])
        analysts = {k: AgentDefinition(description=ROLES[k].title, prompt=ROLES[k].system_prompt(),
                                       tools=[f"mcp__research__{t}" for t in ROLES[k].tools], model="inherit")
                    for k in PARALLEL}
        lead = ("You are the Lead Agent of a trading workflow. Delegate to EACH of these research subagents exactly once "
                f"(they are independent - run them in parallel if you can): {', '.join(PARALLEL)}. Pass each one the "
                f"symbol {ctx['symbol']}. Then reply with one JSON object mapping each subagent name to the JSON it returned.")
        text, msgs = asyncio.run(asyncio.wait_for(
            self._ask(lead, f"Research {ctx['symbol']}.", agents=analysts, mcp_servers={"research": server},
                      allowed_tools=[f"mcp__research__{t}" for t in names] + ["Agent", "Task"],
                      disallowed_tools=["Bash", "Write", "Edit", "Read", "WebFetch", "WebSearch"], max_turns=12),
            get_settings().agent_timeout_s))
        out: dict[str, dict] = {}
        calls: dict[str, str] = {}
        for m in msgs:
            for b in getattr(m, "content", []) or []:
                if isinstance(b, ToolUseBlock) and b.name in ("Agent", "Task"):
                    calls[b.id] = (b.input or {}).get("subagent_type", "")
                elif isinstance(m, UserMessage) and isinstance(b, ToolResultBlock) and b.tool_use_id in calls:
                    content = b.content if isinstance(b.content, str) else " ".join(
                        c.get("text", "") for c in (b.content or []) if isinstance(c, dict))
                    try:
                        out[calls[b.tool_use_id]] = parse_json(content)
                    except Exception:
                        continue
        if len(out) < len(PARALLEL):
            try:
                out = {**parse_json(text), **out}
            except Exception:
                pass
        return {k: v for k, v in out.items() if k in ROLES}


# =========================================================================== OpenAI Agents SDK
def parse_openai_items(items: list, tool_to_role: dict[str, str]) -> dict[str, dict]:
    """Map agents-as-tools outputs (ToolCallOutputItem) back to their agent role."""
    calls, out = {}, {}
    for it in items:
        raw = getattr(it, "raw_item", None)
        typ = getattr(it, "type", "")
        if typ == "tool_call_item":
            name = getattr(raw, "name", None) or (raw.get("name") if isinstance(raw, dict) else None)
            cid = getattr(raw, "call_id", None) or (raw.get("call_id") if isinstance(raw, dict) else None)
            if name in tool_to_role:
                calls[cid] = tool_to_role[name]
        elif typ == "tool_call_output_item":
            cid = raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None)
            if cid in calls:
                try:
                    out[calls[cid]] = parse_json(str(getattr(it, "output", "")))
                except Exception:
                    continue
    return out


class OpenAIAgentsProvider(Provider):
    name = "openai"
    label = "OpenAI (OpenAI Agents SDK)"
    supports_native = True
    auth_mode = "api_key"

    def __init__(self, model: str | None = None):
        super().__init__(model or get_settings().openai_model)

    def available(self) -> tuple[bool, str]:
        try:
            import agents  # noqa: F401
        except ImportError:
            return False, "openai-agents not installed (uv sync --extra ai)"
        if not get_settings().openai_api_key:
            return False, "set OPENAI_API_KEY (the Agents SDK has no ChatGPT login - use the 'codex' provider for that)"
        return True, "OpenAI Agents SDK via OPENAI_API_KEY"

    def _agent(self, role: Role, ctx: dict, reports: dict):
        from agents import Agent, function_tool

        tools = []
        for t in role.tools:
            def make(tname):
                @function_tool(name_override=tname, description_override=TOOL_DOCS[tname])
                def _f() -> str:
                    return json.dumps(tool_payload(tname, ctx, reports), default=str)
                return _f
            tools.append(make(t))
        kw = {"model": self.model} if self.model else {}
        return Agent(name=role.title, instructions=role.system_prompt(), tools=tools, **kw)

    def complete(self, system: str, prompt: str) -> str:
        from agents import Agent, Runner, set_default_openai_key
        set_default_openai_key(get_settings().openai_api_key)
        kw = {"model": self.model} if self.model else {}
        res = Runner.run_sync(Agent(name="Strategy author", instructions=system, **kw), prompt, max_turns=1)
        return str(res.final_output)

    def run_role(self, role: Role, ctx: dict, reports: dict, round_no: int = 1) -> dict:
        from agents import Runner, set_default_openai_key
        set_default_openai_key(get_settings().openai_api_key)
        res = Runner.run_sync(self._agent(role, ctx, reports), role_prompt(role, ctx, reports, round_no), max_turns=4)
        return parse_json(str(res.final_output))

    def run_native(self, ctx: dict, reports: dict) -> dict[str, dict]:
        """Lead agent that calls the two research agents as tools (agents-as-tools)."""
        from agents import Agent, Runner, set_default_openai_key
        set_default_openai_key(get_settings().openai_api_key)
        tool_to_role = {}
        tools = []
        for k in PARALLEL:
            tname = f"ask_{k}"
            tool_to_role[tname] = k
            tools.append(self._agent(ROLES[k], ctx, reports).as_tool(tool_name=tname, tool_description=ROLES[k].title))
        kw = {"model": self.model} if self.model else {}
        lead = Agent(name="Lead Agent", tools=tools, **kw,
                     instructions="Call each research agent tool exactly once for the symbol, then reply with one JSON "
                                  "object mapping agent name to its JSON.")
        res = Runner.run_sync(lead, f"Research {ctx['symbol']}.", max_turns=8)
        return parse_openai_items(res.new_items, tool_to_role)


# =========================================================================== Codex (ChatGPT login)
_CODEX_STATUS: dict[str, Any] = {"t": 0.0, "value": None}


def codex_binary() -> str | None:
    return shutil.which("codex")


def codex_login_status(force: bool = False) -> dict:
    """Login state of the user's own Codex CLI (never reads token files). Cached for 60 s."""
    if not force and _CODEX_STATUS["value"] and time.time() - _CODEX_STATUS["t"] < 60:
        return _CODEX_STATUS["value"]
    st = {"installed": False, "logged_in": False, "method": None, "detail": ""}
    try:
        import openai_codex  # noqa: F401
        st["installed"], st["sdk"] = True, "openai-codex"
    except ImportError:
        st["sdk"] = None
    exe = codex_binary()
    if exe:
        st["installed"] = True
        try:
            p = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=15)
            txt = (p.stdout + p.stderr).strip()
            st["detail"] = txt.splitlines()[0] if txt else ""
            st["logged_in"] = p.returncode == 0 and "not logged in" not in txt.lower()
            st["method"] = "chatgpt" if "chatgpt" in txt.lower() else "api_key" if "api key" in txt.lower() else None
        except Exception as exc:
            st["detail"] = f"codex login status failed: {exc}"
    elif st["sdk"]:
        st["detail"] = "Codex SDK installed; open the Integrations page and click Test to check the login"
    _CODEX_STATUS.update(t=time.time(), value=st)
    return st


class CodexProvider(Provider):
    name = "codex"
    label = "OpenAI Codex (Sign in with ChatGPT)"

    def __init__(self, model: str | None = None):
        super().__init__(model or get_settings().codex_model)
        self.auth_mode = "chatgpt_login"

    def available(self) -> tuple[bool, str]:
        st = codex_login_status()
        if not st["installed"]:
            return False, "install the Codex CLI / SDK (uv sync --extra ai) and run: codex login"
        if not st["logged_in"]:
            return False, "not logged in - run: codex login (Sign in with ChatGPT)"
        self.auth_mode = "chatgpt_login" if st.get("method") == "chatgpt" else "api_key"
        return True, st.get("detail") or "logged in"

    def complete(self, system: str, prompt: str) -> str:
        try:
            from openai_codex import ApprovalMode, Codex, Sandbox
            with Codex() as codex:
                kw = {"model": self.model} if self.model else {}
                th = codex.thread_start(base_instructions=system, ephemeral=True, sandbox=Sandbox.read_only,
                                        approval_mode=ApprovalMode.deny_all, **kw)
                return th.run(prompt, output_schema=None).final_response or ""
        except ImportError:
            pass
        exe = codex_binary()
        if not exe:
            raise ProviderError("Codex CLI not found")
        p = subprocess.run([exe, "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
                            *(["-m", self.model] if self.model else []), f"{system}\n\n{prompt}"],
                           capture_output=True, text=True, timeout=get_settings().agent_timeout_s)
        if p.returncode != 0:
            raise ProviderError(p.stderr[-500:])
        return p.stdout

    def run_role(self, role: Role, ctx: dict, reports: dict, round_no: int = 1) -> dict:
        schema = {"type": "object", "properties": {k: {} for k in role.output}, "required": list(role.output),
                  "additionalProperties": True}
        prompt = role_prompt(role, ctx, reports, round_no)
        try:
            from openai_codex import ApprovalMode, Codex, Sandbox
            with Codex() as codex:
                kw = {"model": self.model} if self.model else {}
                th = codex.thread_start(base_instructions=role.system_prompt(), ephemeral=True, sandbox=Sandbox.read_only,
                                        approval_mode=ApprovalMode.deny_all, **kw)
                res = th.run(prompt, output_schema=None)
                return parse_json(res.final_response or "")
        except ImportError:
            pass
        exe = codex_binary()
        if not exe:
            raise ProviderError("Codex CLI not found")
        p = subprocess.run([exe, "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
                            *(["-m", self.model] if self.model else []), f"{role.system_prompt()}\n\n{prompt}"],
                           capture_output=True, text=True, timeout=get_settings().agent_timeout_s)
        if p.returncode != 0:
            raise ProviderError(p.stderr[-500:])
        _ = schema
        return parse_json(p.stdout)


PROVIDERS = {"rules": RulesProvider, "claude": ClaudeProvider, "openai": OpenAIAgentsProvider, "codex": CodexProvider}


def resolve(name: str | None = None) -> Provider:
    """'auto' prefers subscription login (Codex), then API-key providers, then the rule brains."""
    name = (name or get_settings().ai_provider or "auto").lower()
    if name != "auto":
        return PROVIDERS.get(name, RulesProvider)()
    for n in ("codex", "claude", "openai"):
        p = PROVIDERS[n]()
        ok, _ = p.available()
        if ok:
            return p
    return RulesProvider()


def status_all() -> list[dict]:
    out = []
    for n, cls in PROVIDERS.items():
        p = cls()
        ok, msg = p.available()
        out.append({"name": n, "label": p.label, "available": ok, "message": msg, "auth_mode": p.auth_mode,
                    "model": p.model, "native_multi_agent": p.supports_native, "terms": TERMS.get(n)})
    return out
