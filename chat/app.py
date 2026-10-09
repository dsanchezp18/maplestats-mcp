# ============================================================
# MapleStats chat demo
# Author: Daniel Sanchez
# Purpose: Serve a one-page chat in which a cheap LLM answers questions about
#          Canadian open data by calling the public MapleStats MCP server.
#          Two backends, chosen by CHAT_PROVIDER: "anthropic" (Anthropic's MCP
#          connector runs the tool loop) or "openai" (any OpenAI-compatible API,
#          such as DeepSeek, GLM or Kimi; this app runs the tool loop).
# Inputs:  POST /api/chat with the conversation so far
# Outputs: JSON with the answer and the MCP tool calls the model made
# ============================================================

import json
import logging
import os
import time
from collections import deque
from datetime import date
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from fastmcp import Client
from openai import AsyncOpenAI
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

# 0. Setup ----

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("maplestats_chat")

STATIC_DIR = Path(__file__).parent / "static"

PROVIDER = os.environ.get("CHAT_PROVIDER", "anthropic")
MODEL = os.environ.get("CHAT_MODEL", "claude-haiku-5-5")
API_KEY = os.environ.get("CHAT_API_KEY", "")
BASE_URL = os.environ.get("CHAT_BASE_URL", "")
MCP_URL = os.environ.get("CHAT_MCP_URL", "https://maplestats-mcp.onrender.com/mcp")
EFFORT = os.environ.get("CHAT_EFFORT", "low")

# Limits protect the key's budget: this endpoint is public and every call costs money.
MAX_USER_TURNS = int(os.environ.get("CHAT_MAX_USER_TURNS", "8"))
MAX_MESSAGE_CHARS = int(os.environ.get("CHAT_MAX_MESSAGE_CHARS", "1000"))
MAX_OUTPUT_TOKENS = int(os.environ.get("CHAT_MAX_OUTPUT_TOKENS", "2000"))
MAX_TOOL_STEPS = int(os.environ.get("CHAT_MAX_TOOL_STEPS", "8"))
TOOL_RESULT_CHARS = int(os.environ.get("CHAT_TOOL_RESULT_CHARS", "20000"))
RATE_PER_HOUR = int(os.environ.get("CHAT_RATE_PER_HOUR", "20"))
DAILY_LIMIT = int(os.environ.get("CHAT_DAILY_LIMIT", "500"))
ALLOWED_ORIGINS = [
    origin for origin in os.environ.get("CHAT_ALLOWED_ORIGINS", "").split(",") if origin
]

SYSTEM_PROMPT = (
    "You answer questions about Canadian open data (Statistics Canada, provincial "
    "agencies and other federal sources) using the MapleStats tools.\n"
    "- For any data question, call plan_query first, then follow its plan with "
    "search_tools and call_tool. Never answer a numeric question from memory.\n"
    "- Quote the figures the tools returned, with the reference period and the "
    "source table or agency. If a tool fails or returns nothing, say so; do not "
    "guess.\n"
    "- Answer in the user's language (English or French), briefly. Use a small "
    "table when comparing several values."
)

# 1. Rate limiting ----

_hits_by_client: dict[str, deque[float]] = {}
_daily_count: dict[str, Any] = {"day": date.today(), "n": 0}


def client_address(request: Request) -> str:
    """Return the caller's address, read one hop from the right of X-Forwarded-For.

    What the caller writes sits on the left and can be forged; the host's proxy
    appends the real address on the right (same rule as the MCP server).
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def over_limit(address: str) -> str | None:
    """Record one request and return a reason if the caller or the day is over."""
    now = time.time()
    today = date.today()
    if _daily_count["day"] != today:
        _daily_count.update(day=today, n=0)
    if _daily_count["n"] >= DAILY_LIMIT:
        return "The demo has reached its daily limit. Please try again tomorrow."

    hits = _hits_by_client.setdefault(address, deque())
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= RATE_PER_HOUR:
        return "Too many questions from this address. Please try again later."

    hits.append(now)
    _daily_count["n"] += 1
    return None


# 2. Model backends ----


def describe_call(name: str, arguments: Any) -> dict[str, Any]:
    """Unwrap the server's call_tool so the page shows the real tool name."""
    if name == "call_tool" and isinstance(arguments, dict):
        return {
            "name": str(arguments.get("name", name)),
            "arguments": arguments.get("arguments", {}),
        }
    return {"name": name, "arguments": arguments}


def parse_arguments(raw: str) -> dict[str, Any]:
    """Parse a tool call's JSON arguments; models occasionally send bad JSON."""
    try:
        parsed = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def ask_anthropic(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Let Anthropic's MCP connector call the public MapleStats server."""
    client = AsyncAnthropic(api_key=API_KEY or None)
    conversation: list[dict[str, Any]] = list(messages)
    tools_used: list[dict[str, Any]] = []

    for _ in range(MAX_TOOL_STEPS):
        response = await client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_OUTPUT_TOKENS,
            betas=["mcp-client-2025-11-20"],
            system=SYSTEM_PROMPT,
            output_config={"effort": EFFORT},
            mcp_servers=[{"type": "url", "url": MCP_URL, "name": "maplestats"}],
            tools=[{"type": "mcp_toolset", "mcp_server_name": "maplestats"}],
            messages=conversation,
        )
        for block in response.content:
            if block.type == "mcp_tool_use":
                tools_used.append(describe_call(block.name, block.input))
        # pause_turn means the server paused a long turn; resume it unchanged.
        if response.stop_reason != "pause_turn":
            break
        conversation.append({"role": "assistant", "content": response.content})

    answer = "".join(block.text for block in response.content if block.type == "text")
    return {"answer": answer, "tools_used": tools_used}


_openai_tools: list[dict[str, Any]] = []


async def ask_openai_compatible(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Run the tool loop here, against any OpenAI-compatible chat API."""
    client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL or None)
    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *messages,
    ]
    tools_used: list[dict[str, Any]] = []

    async with Client(MCP_URL) as mcp:
        # The server exposes three tools and they do not change per request.
        if not _openai_tools:
            for tool in await mcp.list_tools():
                _openai_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": tool.inputSchema,
                        },
                    }
                )

        for _ in range(MAX_TOOL_STEPS):
            response = await client.chat.completions.create(
                model=MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                messages=conversation,
                tools=_openai_tools,
            )
            message = response.choices[0].message
            if not message.tool_calls:
                return {"answer": message.content or "", "tools_used": tools_used}

            conversation.append(message.model_dump(exclude_none=True))
            for call in message.tool_calls:
                arguments = parse_arguments(call.function.arguments)
                tools_used.append(describe_call(call.function.name, arguments))
                result = await mcp.call_tool(
                    call.function.name, arguments, raise_on_error=False
                )
                text = "\n".join(
                    part.text for part in result.content if hasattr(part, "text")
                )
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": text[:TOOL_RESULT_CHARS],
                    }
                )

    return {
        "answer": "I could not finish within the tool-call limit. Try a narrower "
        "question.",
        "tools_used": tools_used,
    }


async def ask_model(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Dispatch to the backend chosen by CHAT_PROVIDER."""
    if PROVIDER == "openai":
        return await ask_openai_compatible(messages)
    return await ask_anthropic(messages)


# 3. HTTP routes ----


def validate_messages(payload: Any) -> list[dict[str, str]] | str:
    """Return the cleaned conversation, or a message naming what is wrong."""
    raw = payload.get("messages") if isinstance(payload, dict) else None
    if not isinstance(raw, list) or not raw:
        return "Send a non-empty 'messages' list."

    messages: list[dict[str, str]] = []
    for item in raw:
        role = item.get("role") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        if role not in ("user", "assistant") or not isinstance(content, str):
            return "Each message needs a 'role' (user or assistant) and text 'content'."
        if not content.strip() or len(content) > MAX_MESSAGE_CHARS:
            return f"Messages must be 1 to {MAX_MESSAGE_CHARS} characters."
        messages.append({"role": role, "content": content})

    if messages[-1]["role"] != "user":
        return "The last message must come from the user."
    if sum(1 for m in messages if m["role"] == "user") > MAX_USER_TURNS:
        return "This conversation is long enough. Please start a new one."
    return messages


async def chat(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)

    messages = validate_messages(payload)
    if isinstance(messages, str):
        return JSONResponse({"error": messages}, status_code=400)

    reason = over_limit(client_address(request))
    if reason:
        return JSONResponse({"error": reason}, status_code=429)

    try:
        return JSONResponse(await ask_model(messages))
    except Exception:
        logger.exception("Model backend failed")
        return JSONResponse(
            {"error": "The model or the data server did not answer. Try again."},
            status_code=502,
        )


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "provider": PROVIDER, "model": MODEL})


async def index(request: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app = Starlette(
    routes=[
        Route("/", index),
        Route("/health", health),
        Route("/api/chat", chat, methods=["POST"]),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=ALLOWED_ORIGINS,
            allow_methods=["POST"],
            allow_headers=["content-type"],
        )
    ],
)
