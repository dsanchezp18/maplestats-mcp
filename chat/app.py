# ============================================================
# MapleStats chat demo
# Author: Daniel Sanchez
# Purpose: Serve a one-page chat in which a cheap LLM answers questions about
#          Canadian open data by calling the public MapleStats MCP server.
#          Two backends, chosen by CHAT_PROVIDER: "anthropic" (Anthropic's MCP
#          connector runs the tool loop) or "openai" (any OpenAI-compatible API,
#          such as DeepSeek, GLM or Kimi; this app runs the tool loop).
# Inputs:  POST /api/chat with the conversation so far
# Outputs: JSON with the answer, the MCP tool calls the model made, and the
#          series and sources those calls returned (drawn by the page)
# ============================================================

import base64
import hashlib
import ipaddress
import json
import logging
import os
import re
import time
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anthropic import AsyncAnthropic
from fastmcp import Client
from openai import AsyncOpenAI
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import results

# 0. Setup ----

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("maplestats_chat")

STATIC_DIR = Path(__file__).parent / "static"

PROVIDER = os.environ.get("CHAT_PROVIDER", "anthropic")
MODEL = os.environ.get("CHAT_MODEL", "claude-haiku-5-5")
API_KEY = os.environ.get("CHAT_API_KEY", "")
BASE_URL = os.environ.get("CHAT_BASE_URL", "")
MCP_URL = os.environ.get("CHAT_MCP_URL", "https://mcp.maplestats.danielstats.io/mcp")
EFFORT = os.environ.get("CHAT_EFFORT", "low")

# Limits protect the key's budget: this endpoint is public and every call costs money.
MAX_USER_TURNS = int(os.environ.get("CHAT_MAX_USER_TURNS", "8"))
MAX_MESSAGE_CHARS = int(os.environ.get("CHAT_MAX_MESSAGE_CHARS", "1000"))
MAX_ASSISTANT_CHARS = int(os.environ.get("CHAT_MAX_ASSISTANT_CHARS", "16000"))
MAX_CONVERSATION_CHARS = int(os.environ.get("CHAT_MAX_CONVERSATION_CHARS", "120000"))
MAX_BODY_BYTES = int(os.environ.get("CHAT_MAX_BODY_BYTES", "524288"))
MAX_OUTPUT_TOKENS = int(os.environ.get("CHAT_MAX_OUTPUT_TOKENS", "2000"))
MAX_TOOL_STEPS = int(os.environ.get("CHAT_MAX_TOOL_STEPS", "8"))
TOOL_RESULT_CHARS = int(os.environ.get("CHAT_TOOL_RESULT_CHARS", "20000"))
RATE_PER_HOUR = int(os.environ.get("CHAT_RATE_PER_HOUR", "20"))
DAILY_LIMIT = int(os.environ.get("CHAT_DAILY_LIMIT", "500"))
# Input plus output tokens, summed from every model call's usage, across all
# callers. The caps above count questions; this one counts what is billed.
DAILY_TOKENS = int(os.environ.get("CHAT_DAILY_TOKENS", "3000000"))
ALLOWED_ORIGINS = [
    origin for origin in os.environ.get("CHAT_ALLOWED_ORIGINS", "").split(",") if origin
]


def trusts_proxy_headers(environ: Mapping[str, str]) -> bool:
    """Whether the rate limit may read X-Forwarded-For.

    The header is forgeable unless a trusted proxy sits in front, so it is read
    only when CHAT_TRUST_PROXY_HEADERS says so. Render sets RENDER for every
    service it runs and always puts its proxy in front, so the flag defaults on
    there and off everywhere else.
    """
    default = "1" if environ.get("RENDER") else "0"
    raw = environ.get("CHAT_TRUST_PROXY_HEADERS", default)
    return raw.strip().lower() in {"1", "true", "yes", "on"}


TRUST_PROXY_HEADERS = trusts_proxy_headers(os.environ)


def client_ip_header(environ: Mapping[str, str]) -> str | None:
    """The header the outermost proxy sets to the caller's own address, if any.

    Render's onrender.com hostnames sit behind Cloudflare, which sets
    CF-Connecting-IP, so the default is that header when RENDER is set and none
    elsewhere. CHAT_CLIENT_IP_HEADER overrides it; set it to an empty string to
    turn it off. It is read only when proxy headers are trusted.
    """
    default = "CF-Connecting-IP" if environ.get("RENDER") else ""
    name = environ.get("CHAT_CLIENT_IP_HEADER", default).strip()
    return name or None


CLIENT_IP_HEADER = client_ip_header(os.environ)

SYSTEM_PROMPT = (
    "You answer questions about Canadian open data (Statistics Canada, provincial "
    "agencies and other federal sources) using the MapleStats tools.\n"
    "- For any data question, call plan_query first, then follow its plan with "
    "search_tools and call_tool. Never answer a numeric question from memory.\n"
    "- For rankings, totals and 'top N' questions, first call search_tools with "
    "the words 'top' or 'ranking' plus the topic, and use a purpose-built tool "
    "(for example cimt_get_top_commodities for trade) instead of a raw-row tool. "
    "If a result says it was truncated or returned only part of the rows, never "
    "rank, total or compare from it: call a tool that aggregates, or say plainly "
    "that you could not get the full result.\n"
    "- Quote the figures the tools returned, with the reference period and the "
    "source table or agency. If a tool fails or returns nothing, say so; do not "
    "guess.\n"
    "- Write only the final answer. Do not narrate your steps or mention tools "
    "you are about to try.\n"
    "- Answer in the user's language (English or French), briefly. Use a small "
    "table when comparing several values.\n"
    "- You can make only a few tool calls per question. When a tool accepts "
    "several places or series at once, ask for them in one call. If you cannot "
    "get everything, answer with what you have and say what is missing."
)

# Shown instead of an empty answer, so a visitor learns what to change. Each one
# follows a model call that completed and was billed.
STEP_LIMIT_ANSWER = (
    "I could not finish within the demo's tool-call limit. Try a narrower "
    "question, for example fewer places or a shorter period."
)
LENGTH_LIMIT_ANSWER = (
    "The answer was longer than the demo allows and was cut off. Try a "
    "narrower question, for example fewer places or a shorter period."
)
CUT_OFF_NOTE = "\n\n_(Cut off at the demo's length limit.)_"
DATA_SERVER_ANSWER = (
    "The data server returned errors for this question; it may be restarting. "
    "Try again in a minute."
)

# 1. Rate limiting ----

_hits_by_client: dict[str, deque[float]] = {}
_daily_count: dict[str, Any] = {"day": datetime.now(UTC).date(), "n": 0}
_daily_tokens: dict[str, Any] = {"day": datetime.now(UTC).date(), "n": 0}


def client_address(request: Request) -> str:
    """Return the caller's address for the rate limit.

    With CHAT_TRUST_PROXY_HEADERS on (the default on Render), first read
    CHAT_CLIENT_IP_HEADER (CF-Connecting-IP on Render), which the outermost
    proxy sets to the caller's own address; when it is absent or not an IP
    address, read one hop from the right of X-Forwarded-For: what the caller
    writes sits on the left and can be forged, while the host's proxy appends
    the real address on the right (same rules as the MCP server). Behind
    Cloudflare and Render's balancer, that rightmost entry can be a shared edge
    address, which is why the dedicated header comes first. With proxy headers
    off, both are ignored, because a service reached directly would let any
    caller choose its own bucket.
    """
    if TRUST_PROXY_HEADERS and CLIENT_IP_HEADER:
        raw = request.headers.get(CLIENT_IP_HEADER.lower(), "")
        try:
            return str(ipaddress.ip_address(raw.split(",")[0].strip()))
        except ValueError:
            pass
    forwarded = request.headers.get("x-forwarded-for", "")
    if TRUST_PROXY_HEADERS and forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _tokens_today() -> dict[str, Any]:
    today = datetime.now(UTC).date()
    if _daily_tokens["day"] != today:
        _daily_tokens.update(day=today, n=0)
    return _daily_tokens


def add_tokens(usage: Any) -> None:
    """Add one model call's billed tokens (input, cached input and output).

    Reads Anthropic's usage (input_tokens, output_tokens and the cache fields)
    and the OpenAI-compatible one (prompt_tokens, completion_tokens). Never
    raises: a response without usage adds nothing.
    """
    fields = (
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "prompt_tokens",
        "completion_tokens",
    )
    total = 0
    for field in fields:
        value = getattr(usage, field, None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            total += value
    _tokens_today()["n"] += total


def over_limit(address: str) -> str | None:
    """Record one request and return a reason if the caller or the day is over."""
    now = time.time()
    today = datetime.now(UTC).date()
    if _daily_count["day"] != today:
        _daily_count.update(day=today, n=0)
    if _daily_count["n"] >= DAILY_LIMIT:
        return "The demo has reached its daily limit. Please try again tomorrow."
    if _tokens_today()["n"] >= DAILY_TOKENS:
        return (
            "The demo has used its model budget for today. Please try again tomorrow."
        )

    # Drop every client whose hits have all aged out, so the table holds only
    # addresses seen in the last hour instead of every address ever seen.
    for key in list(_hits_by_client):
        old_hits = _hits_by_client[key]
        while old_hits and now - old_hits[0] > 3600:
            old_hits.popleft()
        if not old_hits:
            del _hits_by_client[key]

    hits = _hits_by_client.setdefault(address, deque())
    if len(hits) >= RATE_PER_HOUR:
        return "Too many questions from this address. Please try again later."

    hits.append(now)
    _daily_count["n"] += 1
    return None


def refund(address: str) -> None:
    """Give back the request over_limit just counted, when no model call was billed."""
    hits = _hits_by_client.get(address)
    if hits:
        hits.pop()
        if not hits:
            del _hits_by_client[address]
    _daily_count["n"] = max(0, _daily_count["n"] - 1)


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


def final_text(content: list[Any]) -> str:
    """Return only the text written after the last tool block.

    Text before a tool call is the model thinking aloud ("I'll check whether...");
    joining it with the real answer showed visitors a conclusion next to a
    half-finished plan.
    """
    last_tool = max(
        (i for i, block in enumerate(content) if block.type.startswith("mcp_tool")),
        default=-1,
    )
    return "".join(
        block.text for block in content[last_tool + 1 :] if block.type == "text"
    ).strip()


class BackendFailure(Exception):
    """A backend error, with whether a model call had already completed.

    A completed call has been billed, so the request still counts against the
    limits; only a failure before any call completed is given back. Anything
    raised after a billed call, including while reading its result, is
    reported with billed=True.
    """

    def __init__(self, billed: bool) -> None:
        super().__init__("Model backend failed")
        self.billed = billed


async def ask_anthropic(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Let Anthropic's MCP connector call the public MapleStats server."""
    conversation: list[dict[str, Any]] = list(messages)
    tools_used: list[dict[str, Any]] = []
    # (tool name, result text) for every successful call, in order, for the page.
    returned: list[tuple[str, Any]] = []
    names: dict[str, str] = {}
    tool_errors = 0
    model_calls = 0
    billed = False

    try:
        # The client owns an HTTP connection pool, so close it when the request ends.
        async with AsyncAnthropic(api_key=API_KEY or None) as client:
            for _ in range(max(1, MAX_TOOL_STEPS)):
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
                billed = True
                add_tokens(getattr(response, "usage", None))
                model_calls += 1
                for block in response.content:
                    if block.type == "mcp_tool_use":
                        call = describe_call(block.name, block.input)
                        tools_used.append(call)
                        names[str(getattr(block, "id", ""))] = call["name"]
                    elif block.type == "mcp_tool_result":
                        if getattr(block, "is_error", False):
                            tool_errors += 1
                        else:
                            name = names.get(str(getattr(block, "tool_use_id", "")), "")
                            content = getattr(block, "content", None)
                            returned.append((name, results.text_of(content)))
                # pause_turn means the server paused a long turn; resume it unchanged.
                if response.stop_reason != "pause_turn":
                    break
                conversation.append({"role": "assistant", "content": response.content})

        # Still inside the try: the calls above were billed, so a failure while
        # reading their result must not be refunded.
        answer = final_text(response.content)
        # Counts and the stop reason only, never the question or the answer: enough
        # to tell a step limit, a length limit and a data-server failure apart.
        logger.info(
            "Turn ended: stop_reason=%s, model calls %d, tool calls %d, "
            "tool errors %d, answer %s",
            response.stop_reason,
            model_calls,
            len(tools_used),
            tool_errors,
            "yes" if answer else "empty",
        )
        if response.stop_reason == "pause_turn":  # still working after the last resume
            answer = answer or STEP_LIMIT_ANSWER
        elif response.stop_reason == "max_tokens":
            answer = answer + CUT_OFF_NOTE if answer else LENGTH_LIMIT_ANSWER
        elif not answer and tool_errors:
            answer = DATA_SERVER_ANSWER
        return {"answer": answer, "tools_used": tools_used, **results.collect(returned)}
    except Exception as error:  # reported with whether it cost money
        raise BackendFailure(billed) from error


_openai_tools: list[dict[str, Any]] = []


async def load_openai_tools(mcp: Client) -> list[dict[str, Any]]:
    """The server's tools in OpenAI format, fetched once per process.

    The list is built locally and assigned in one step: two first requests
    arriving together would otherwise both append, leaving duplicate function
    names that the API rejects on every later request.
    """
    if not _openai_tools:
        built = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
            for tool in await mcp.list_tools()
        ]
        _openai_tools[:] = built
    return _openai_tools


async def ask_openai_compatible(messages: list[dict[str, str]]) -> dict[str, Any]:
    """Run the tool loop here, against any OpenAI-compatible chat API."""
    conversation: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *messages,
    ]
    tools_used: list[dict[str, Any]] = []
    returned: list[tuple[str, Any]] = []
    billed = False

    try:
        # The OpenAI client owns an HTTP connection pool, so close it when the request ends.
        async with (
            AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL or None) as client,
            Client(MCP_URL) as mcp,
        ):
            # The server exposes three tools and they do not change per request.
            tools = await load_openai_tools(mcp)

            for _ in range(MAX_TOOL_STEPS):
                response = await client.chat.completions.create(
                    model=MODEL,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    messages=conversation,
                    tools=tools,
                )
                billed = True
                add_tokens(getattr(response, "usage", None))
                message = response.choices[0].message
                if not message.tool_calls:
                    return {
                        "answer": message.content or "",
                        "tools_used": tools_used,
                        **results.collect(returned),
                    }

                conversation.append(message.model_dump(exclude_none=True))
                for call in message.tool_calls:
                    arguments = parse_arguments(call.function.arguments)
                    described = describe_call(call.function.name, arguments)
                    tools_used.append(described)
                    result = await mcp.call_tool(
                        call.function.name, arguments, raise_on_error=False
                    )
                    text = "\n".join(
                        part.text for part in result.content if hasattr(part, "text")
                    )
                    if not result.is_error:
                        returned.append(
                            (described["name"], result.structured_content or text)
                        )
                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": text[:TOOL_RESULT_CHARS],
                        }
                    )

        # Still inside the try, so a failure here is reported as billed.
        return {
            "answer": STEP_LIMIT_ANSWER,
            "tools_used": tools_used,
            **results.collect(returned),
        }
    except Exception as error:  # reported with whether it cost money
        raise BackendFailure(billed) from error


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

    if len(raw) > 2 * MAX_USER_TURNS - 1:
        return "This conversation is long enough. Please start a new one."
    messages: list[dict[str, str]] = []
    total_chars = 0
    for index, item in enumerate(raw):
        role = item.get("role") if isinstance(item, dict) else None
        content = item.get("content") if isinstance(item, dict) else None
        if role not in ("user", "assistant") or not isinstance(content, str):
            return "Each message needs a 'role' (user or assistant) and text 'content'."
        if role != ("user" if index % 2 == 0 else "assistant"):
            return "Messages must alternate between user and assistant, starting with user."
        limit = MAX_MESSAGE_CHARS if role == "user" else MAX_ASSISTANT_CHARS
        if not content.strip() or len(content) > limit:
            return f"{role.capitalize()} messages must be 1 to {limit} characters."
        total_chars += len(content)
        if total_chars > MAX_CONVERSATION_CHARS:
            return "This conversation is too large. Please start a new one."
        messages.append({"role": role, "content": content})

    if messages[-1]["role"] != "user":
        return "The last message must come from the user."
    if sum(1 for m in messages if m["role"] == "user") > MAX_USER_TURNS:
        return "This conversation is long enough. Please start a new one."
    return messages


async def chat(request: Request) -> JSONResponse:
    # A page on any other site can send a "simple" cross-site POST (text/plain,
    # no preflight) from its visitors' browsers; CORSMiddleware only withholds
    # response headers and never rejects the request. A JSON content type is not
    # a simple one, so the browser must preflight it, and the preflight fails
    # for every origin not in CHAT_ALLOWED_ORIGINS.
    content_type = request.headers.get("content-type", "").strip().lower()
    if not content_type.startswith("application/json"):
        return JSONResponse(
            {"error": "Content-Type must be application/json."}, status_code=415
        )

    try:
        # Check both declared and streamed sizes: chunked requests have no length header.
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return JSONResponse(
                {"error": "Request body is too large."}, status_code=413
            )
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                return JSONResponse(
                    {"error": "Request body is too large."}, status_code=413
                )
            body.extend(chunk)
        payload = json.loads(body)
    except ClientDisconnect:
        # Nobody is left to answer; 499 is the conventional "client closed request".
        return JSONResponse({"error": "Client disconnected."}, status_code=499)
    except (ValueError, UnicodeDecodeError, RecursionError):
        # RecursionError: deeply nested brackets overflow json.loads, and it is not a ValueError.
        return JSONResponse({"error": "Body must be JSON."}, status_code=400)

    messages = validate_messages(payload)
    if isinstance(messages, str):
        return JSONResponse({"error": messages}, status_code=400)

    address = client_address(request)
    reason = over_limit(address)
    if reason:
        return JSONResponse({"error": reason}, status_code=429)

    try:
        result = await ask_model(messages)
        # Keep our own answers valid when the browser sends them back on the next turn.
        answer = str(result.get("answer") or "").strip()
        if not answer:
            # The model call completed and was billed, so the request stays counted.
            return JSONResponse(
                {"error": "The model returned no answer. Try again."}, status_code=502
            )
        result["answer"] = answer[:MAX_ASSISTANT_CHARS]
        return JSONResponse(result)
    except Exception as error:  # noqa: BLE001 - any backend failure is a 502
        failure = error if isinstance(error, BackendFailure) else None
        cause = error.__cause__ if failure and error.__cause__ else error
        # Only the type and status: SDK exception text can echo the question or the request.
        logger.error(
            "Model backend failed (%s, HTTP status %s)",
            type(cause).__name__,
            getattr(cause, "status_code", None),
        )
        # Only a failure known to have happened before any billed call is given
        # back. Anything else (a billed call, or an error whose cost is unknown)
        # stays counted, so retries cannot dodge the caps.
        if failure is not None and not failure.billed:
            refund(address)
        # An unknown model (404) or a rejected key (401, 403) is a fault of this
        # deployment, not a blip: "try again" would send people into a loop.
        if getattr(cause, "status_code", None) in (401, 403, 404):
            return JSONResponse(
                {
                    "error": "The demo is temporarily unavailable. Please try again later."
                },
                status_code=503,
            )
        return JSONResponse(
            {"error": "The model or the data server did not answer. Try again."},
            status_code=502,
        )


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "provider": PROVIDER, "model": MODEL})


# The page is read once, at startup, and served from memory, so the hash of its
# inline script in the policy below always matches the bytes sent: editing the
# page never needs a hand-copied hash, only a restart (which a deploy does).
PAGE = (STATIC_DIR / "index.html").read_bytes()


def inline_script_hashes(page: str) -> list[str]:
    """CSP source expressions ('sha256-...') for every inline <script> in a page."""
    bodies = re.findall(
        r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", page, flags=re.DOTALL
    )
    return [
        "'sha256-"
        + base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode()
        + "'"
        for body in bodies
    ]


# The page-view counter the website also uses: its script, and the endpoint it
# reports to (by beacon or image).
GOATCOUNTER_SCRIPT = "https://gc.zgo.at"
GOATCOUNTER = "https://dsanchezp18.goatcounter.com"


def page_policy(page: str) -> str:
    """The Content-Security-Policy for the page.

    Scripts: this origin, the two pinned CDN files (which also carry SRI hashes)
    and the page's own inline script by hash, so an injected <script> or event
    handler in model output cannot run even if the sanitiser missed it. Styles
    need 'unsafe-inline' for the page's <style> block. frame-ancestors 'none':
    the page asks a ?q= question on arrival when the website links to it, and
    every question is a billed model call, so a page that framed it could spend
    the daily budget from its own visitors' browsers.
    """
    scripts = " ".join(
        [
            "'self'",
            "https://cdnjs.cloudflare.com",
            GOATCOUNTER_SCRIPT,
            *inline_script_hashes(page),
        ]
    )
    return "; ".join(
        [
            "default-src 'self'",
            f"script-src {scripts}",
            "style-src 'self' 'unsafe-inline'",
            f"img-src 'self' data: {GOATCOUNTER}",
            f"connect-src 'self' {GOATCOUNTER}",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        ]
    )


PAGE_HEADERS = {
    "Content-Security-Policy": page_policy(PAGE.decode("utf-8")),
    "X-Frame-Options": "DENY",
}

# Sent on every response, the page and the JSON alike.
COMMON_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
]


class SecurityHeaders:
    """ASGI middleware that adds COMMON_HEADERS to every HTTP response."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Any) -> None:
            if message["type"] == "http.response.start":
                names = {key.lower() for key, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in COMMON_HEADERS if k not in names]
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        await self.app(scope, receive, send_with_headers)


async def index(request: Request) -> Response:
    return Response(PAGE, media_type="text/html; charset=utf-8", headers=PAGE_HEADERS)


app = Starlette(
    routes=[
        Route("/", index),
        Route("/health", health),
        Route("/api/chat", chat, methods=["POST"]),
    ],
    middleware=[
        Middleware(SecurityHeaders),
        Middleware(
            CORSMiddleware,
            allow_origins=ALLOWED_ORIGINS,
            allow_methods=["POST"],
            allow_headers=["content-type"],
        ),
    ],
)
