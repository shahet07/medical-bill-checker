"""LLM clients that return JSON constrained to a schema.

Extraction talks to the JsonLLM protocol only, so providers are swappable.
Content blocks use one neutral shape, converted per provider:
    {"type": "text", "text": "..."}
    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "<b64>"}}

Pick a provider with BILLCHECKER_PROVIDER (gemini | claude) and a model with
BILLCHECKER_MODEL. Credentials come from GEMINI_API_KEY / ANTHROPIC_API_KEY.
"""

import base64
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

DEFAULT_PROVIDER = "gemini"
# gemini-3.8-flash timed out on the free tier in testing (2026-10-29); 3.6 was reliable.
DEFAULT_MODELS = {"gemini": "gemini-3.6-flash", "claude": "claude-opus-5"}
# Claude models that support the server-side refusal fallback.
CLAUDE_FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5-1")
USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
MAX_OUTPUT_TOKENS = 32000

# The SDK warns on every response that carries a thought signature; we read parts directly.
logging.getLogger("google_genai.types").setLevel(logging.ERROR)


@dataclass(frozen=True)
class LLMResponse:
    text: Optional[str]
    stop_reason: str  # "end_turn" | "max_tokens" | "refusal"
    usage: Optional[Dict[str, int]] = None  # token counts, for cost tracking


class LLMUnavailable(Exception):
    """The LLM could not be reached (network, rate limit, 5xx). The job should stay queued."""


class JsonLLM(Protocol):
    def generate(self, system: str, content: List[Dict[str, Any]], schema: Dict[str, Any]) -> LLMResponse: ...


def make_llm(provider: Optional[str] = None, model: Optional[str] = None) -> JsonLLM:
    provider = provider or os.environ.get("BILLCHECKER_PROVIDER", DEFAULT_PROVIDER)
    model = model or os.environ.get("BILLCHECKER_MODEL")
    if provider == "gemini":
        return GeminiJsonLLM(model=model)
    if provider == "claude":
        return ClaudeJsonLLM(model=model)
    raise ValueError("unknown provider {!r}; use 'gemini' or 'claude'".format(provider))


# --- Gemini -----------------------------------------------------------------------

# Finish reasons where the model declined or was blocked rather than finishing.
_GEMINI_BLOCKED = {
    "SAFETY",
    "RECITATION",
    "BLOCKLIST",
    "PROHIBITED_CONTENT",
    "SPII",
    "IMAGE_SAFETY",
    "IMAGE_PROHIBITED_CONTENT",
    "LANGUAGE",
    "OTHER",
}


class GeminiJsonLLM:
    def __init__(self, client: Any = None, model: Optional[str] = None, max_tokens: int = MAX_OUTPUT_TOKENS):
        from google.genai import errors, types

        self._errors = errors
        self._types = types
        if client is None:
            from google import genai

            # The free tier has low per-minute limits; back off and retry on 429/5xx.
            retry = types.HttpRetryOptions(attempts=5, initial_delay=2.0, max_delay=60.0, http_status_codes=[429, 500, 502, 503, 504])
            # Per-attempt timeout in ms; without it a stalled request hangs indefinitely.
            client = genai.Client(http_options=types.HttpOptions(timeout=120_000, retry_options=retry))
        self.client = client
        self.model = model or DEFAULT_MODELS["gemini"]
        self.max_tokens = max_tokens

    def generate(self, system: str, content: List[Dict[str, Any]], schema: Dict[str, Any]) -> LLMResponse:
        t = self._types
        config = t.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            max_output_tokens=self.max_tokens,
        )
        try:
            resp = self.client.models.generate_content(model=self.model, contents=self._parts(content), config=config)
        except self._errors.ServerError as exc:
            raise LLMUnavailable(str(exc)) from exc
        except self._errors.ClientError as exc:
            if exc.code == 429:
                raise LLMUnavailable(str(exc)) from exc
            raise
        except Exception as exc:
            if _is_connection_error(exc):
                raise LLMUnavailable(str(exc)) from exc
            raise
        return LLMResponse(text=_gemini_text(resp), stop_reason=_gemini_stop(resp), usage=_gemini_usage(resp))

    def _parts(self, content: List[Dict[str, Any]]) -> list:
        Part = self._types.Part
        parts = []
        for block in content:
            if block["type"] == "text":
                parts.append(Part.from_text(text=block["text"]))
            elif block["type"] == "image":
                src = block["source"]
                parts.append(Part.from_bytes(data=base64.standard_b64decode(src["data"]), mime_type=src["media_type"]))
            else:
                raise ValueError("unsupported content block type {!r}".format(block["type"]))
        return parts


def _is_connection_error(exc: Exception) -> bool:
    import httpx

    return isinstance(exc, (httpx.TransportError, ConnectionError, TimeoutError))


def _enum_name(value: Any) -> str:
    return getattr(value, "name", None) or str(value or "")


def _gemini_stop(resp: Any) -> str:
    feedback = getattr(resp, "prompt_feedback", None)
    if feedback is not None and getattr(feedback, "block_reason", None):
        return "refusal"
    candidates = getattr(resp, "candidates", None) or []
    if not candidates:
        return "refusal"
    reason = _enum_name(candidates[0].finish_reason)
    if reason == "MAX_TOKENS":
        return "max_tokens"
    if reason in _GEMINI_BLOCKED:
        return "refusal"
    return "end_turn"


def _gemini_text(resp: Any) -> Optional[str]:
    candidates = getattr(resp, "candidates", None) or []
    if not candidates or candidates[0].content is None:
        return None
    # Skip thought summaries; keep only the answer text.
    texts = [p.text for p in (candidates[0].content.parts or []) if getattr(p, "text", None) and not getattr(p, "thought", False)]
    return "".join(texts) or None


def _gemini_usage(resp: Any) -> Optional[Dict[str, int]]:
    u = getattr(resp, "usage_metadata", None)
    if u is None:
        return None
    prompt = u.prompt_token_count or 0
    cached = u.cached_content_token_count or 0
    return {
        "input_tokens": prompt - cached,
        "output_tokens": (u.candidates_token_count or 0) + (u.thoughts_token_count or 0),
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": 0,
    }


# --- Claude -----------------------------------------------------------------------


class ClaudeJsonLLM:
    def __init__(self, client: Any = None, model: Optional[str] = None, max_tokens: int = MAX_OUTPUT_TOKENS):
        import anthropic

        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic()
        self.model = model or DEFAULT_MODELS["claude"]
        self.max_tokens = max_tokens

    def generate(self, system: str, content: List[Dict[str, Any]], schema: Dict[str, Any]) -> LLMResponse:
        kwargs: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
            # Caches the document prefix so the validation retry re-reads it cheaply.
            cache_control={"type": "ephemeral"},
        )
        if self.model in CLAUDE_FALLBACK_MODELS:
            kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        ae = self._anthropic
        try:
            with self.client.beta.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
        except (ae.APIConnectionError, ae.RateLimitError, ae.InternalServerError) as exc:
            raise LLMUnavailable(str(exc)) from exc
        text = next((b.text for b in msg.content if b.type == "text"), None)
        usage = None
        if getattr(msg, "usage", None) is not None:
            usage = {k: getattr(msg.usage, k, None) or 0 for k in USAGE_FIELDS}
        stop = msg.stop_reason if msg.stop_reason in ("max_tokens", "refusal") else "end_turn"
        return LLMResponse(text=text, stop_reason=stop, usage=usage)
