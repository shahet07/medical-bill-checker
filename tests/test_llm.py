import base64
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from google.genai import errors as gerrors
from google.genai import types as gtypes

from billchecker.extraction import BILL_SCHEMA
from billchecker.llm import ClaudeJsonLLM, GeminiJsonLLM, LLMResponse, LLMUnavailable, make_llm

CONTENT = [
    {"type": "text", "text": '<page number="1"> is the image below.'},
    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b"jpegbytes").decode()}},
    {"type": "text", "text": "Transcribe."},
]


# --- Gemini -----------------------------------------------------------------------


def gemini_response(text='{"a": 1}', finish="STOP", block_reason=None, thought=None, candidates=True):
    parts = []
    if thought:
        parts.append(gtypes.Part(text=thought, thought=True))
    if text is not None:
        parts.append(gtypes.Part(text=text))
    return gtypes.GenerateContentResponse(
        candidates=[
            gtypes.Candidate(content=gtypes.Content(role="model", parts=parts), finish_reason=gtypes.FinishReason[finish])
        ]
        if candidates
        else None,
        prompt_feedback=gtypes.GenerateContentResponsePromptFeedback(block_reason=gtypes.BlockedReason[block_reason])
        if block_reason
        else None,
        usage_metadata=gtypes.GenerateContentResponseUsageMetadata(
            prompt_token_count=1000, cached_content_token_count=400, candidates_token_count=300, thoughts_token_count=50
        ),
    )


def gemini_client(response=None, error=None):
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        return response

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)), calls


def test_gemini_request_shape():
    client, calls = gemini_client(gemini_response())
    resp = GeminiJsonLLM(client=client).generate("sys", CONTENT, BILL_SCHEMA)
    assert resp.text == '{"a": 1}' and resp.stop_reason == "end_turn"
    [kw] = calls
    assert kw["model"] == "gemini-3.6-flash"
    cfg = kw["config"]
    assert cfg.system_instruction == "sys"
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema == BILL_SCHEMA
    text1, image, text2 = kw["contents"]
    assert text1.text == '<page number="1"> is the image below.'
    assert image.inline_data.data == b"jpegbytes" and image.inline_data.mime_type == "image/jpeg"
    assert text2.text == "Transcribe."


def test_gemini_usage_mapped_to_common_fields():
    client, _ = gemini_client(gemini_response())
    resp = GeminiJsonLLM(client=client).generate("sys", CONTENT, BILL_SCHEMA)
    assert resp.usage == {
        "input_tokens": 600,
        "output_tokens": 350,
        "cache_read_input_tokens": 400,
        "cache_creation_input_tokens": 0,
    }


def test_gemini_skips_thought_parts():
    client, _ = gemini_client(gemini_response(text='{"ok": true}', thought="let me think"))
    assert GeminiJsonLLM(client=client).generate("sys", CONTENT, BILL_SCHEMA).text == '{"ok": true}'


@pytest.mark.parametrize(
    "kwargs, stop",
    [
        ({"finish": "MAX_TOKENS"}, "max_tokens"),
        ({"finish": "SAFETY", "text": None}, "refusal"),
        ({"finish": "SPII", "text": None}, "refusal"),
        ({"block_reason": "PROHIBITED_CONTENT", "candidates": False}, "refusal"),
        ({"candidates": False}, "refusal"),
    ],
)
def test_gemini_stop_reasons(kwargs, stop):
    client, _ = gemini_client(gemini_response(**kwargs))
    assert GeminiJsonLLM(client=client).generate("sys", CONTENT, BILL_SCHEMA).stop_reason == stop


@pytest.mark.parametrize(
    "error",
    [
        gerrors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}),
        gerrors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}}),
        httpx.ConnectError("no network"),
    ],
)
def test_gemini_outages_raise_unavailable(error):
    client, _ = gemini_client(error=error)
    with pytest.raises(LLMUnavailable):
        GeminiJsonLLM(client=client).generate("sys", CONTENT, BILL_SCHEMA)


def test_gemini_bad_request_raises():
    client, _ = gemini_client(error=gerrors.ClientError(400, {"error": {"code": 400, "message": "bad schema", "status": "INVALID_ARGUMENT"}}))
    with pytest.raises(gerrors.ClientError):
        GeminiJsonLLM(client=client).generate("sys", CONTENT, BILL_SCHEMA)


# --- Claude -----------------------------------------------------------------------


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


def claude_client(message=None, error=None):
    calls = []

    def stream(**kwargs):
        calls.append(kwargs)
        if error:
            raise error
        return FakeStream(message)

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream))), calls


def claude_message(text, stop="end_turn"):
    blocks = [SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=blocks, stop_reason=stop)


def test_claude_request_shape():
    client, calls = claude_client(claude_message('{"a": 1}'))
    resp = ClaudeJsonLLM(client=client).generate("sys", CONTENT, BILL_SCHEMA)
    assert resp == LLMResponse(text='{"a": 1}', stop_reason="end_turn")
    [kw] = calls
    assert kw["model"] == "claude-opus-5"
    assert kw["output_config"] == {"format": {"type": "json_schema", "schema": BILL_SCHEMA}}
    assert kw["cache_control"] == {"type": "ephemeral"}
    assert kw["fallbacks"] == "default"
    assert kw["messages"] == [{"role": "user", "content": CONTENT}]


def test_claude_other_model_has_no_fallbacks():
    client, calls = claude_client(claude_message("{}"))
    ClaudeJsonLLM(client=client, model="claude-sonnet-5").generate("sys", [], BILL_SCHEMA)
    assert calls[0]["model"] == "claude-sonnet-5"
    assert "fallbacks" not in calls[0] and "betas" not in calls[0]


def test_claude_outage_raises_unavailable():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client, _ = claude_client(error=anthropic.APIConnectionError(request=req))
    with pytest.raises(LLMUnavailable):
        ClaudeJsonLLM(client=client).generate("sys", [], BILL_SCHEMA)


def test_claude_bad_request_raises():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.BadRequestError("bad", response=httpx.Response(400, request=req), body=None)
    client, _ = claude_client(error=err)
    with pytest.raises(anthropic.BadRequestError):
        ClaudeJsonLLM(client=client).generate("sys", [], BILL_SCHEMA)


# --- Provider selection -------------------------------------------------------------


def test_make_llm_defaults_to_gemini(monkeypatch):
    monkeypatch.delenv("BILLCHECKER_PROVIDER", raising=False)
    monkeypatch.delenv("BILLCHECKER_MODEL", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    llm = make_llm()
    assert isinstance(llm, GeminiJsonLLM) and llm.model == "gemini-3.6-flash"


def test_make_llm_reads_env(monkeypatch):
    monkeypatch.setenv("BILLCHECKER_PROVIDER", "claude")
    monkeypatch.setenv("BILLCHECKER_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    llm = make_llm()
    assert isinstance(llm, ClaudeJsonLLM) and llm.model == "claude-sonnet-5"


def test_make_llm_rejects_unknown_provider():
    with pytest.raises(ValueError):
        make_llm(provider="other")
