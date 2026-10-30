import json
from typing import Any, Dict, List, Union

import pytest

from billchecker.llm import LLMResponse
from synthetic import build_files


class FakeLLM:
    """Replays scripted responses and records every call. No network, no cost."""

    def __init__(self, *responses: Union[str, Dict, LLMResponse]):
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def generate(self, system, content, schema):
        self.calls.append({"system": system, "content": content, "schema": schema})
        resp = self.responses.pop(0)
        if isinstance(resp, LLMResponse):
            return resp
        if isinstance(resp, dict):
            resp = json.dumps(resp)
        return LLMResponse(text=resp, stop_reason="end_turn")


@pytest.fixture(scope="session")
def fixture_files(tmp_path_factory):
    return build_files(tmp_path_factory.mktemp("fixtures"))
