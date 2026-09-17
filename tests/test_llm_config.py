"""llm.json loading, key resolution, and the Anthropic adapter offline.

No network anywhere: the adapter is tested through an injected fake
client that verifies the payload is built from the frozen request's
fields and nothing else.
"""

import json

import pytest

from audio_lab.llm.adapter import LlmConfigError, LlmNetworkError, LlmResponseError
from audio_lab.llm.anthropic_adapter import AnthropicAdapter
from audio_lab.llm.config import LlmConfig, load_llm_config, resolve_api_key
from audio_lab.llm.types import LlmMessage, LlmRequest


def write_config(tmp_path, payload) -> "Path":
    path = tmp_path / "llm.json"
    path.write_text(json.dumps(payload))
    return path


VALID = {"provider": "anthropic", "model": "claude-opus-5", "api_key_env": "TEST_KEY"}


class TestConfigLoading:
    def test_valid_config(self, tmp_path):
        cfg = load_llm_config(write_config(tmp_path, VALID))
        assert cfg == LlmConfig("anthropic", "claude-opus-5", "TEST_KEY")

    def test_missing_file_is_config_error_with_recipe(self, tmp_path):
        with pytest.raises(LlmConfigError, match="api_key_env"):
            load_llm_config(tmp_path / "absent.json")

    @pytest.mark.parametrize(
        "payload",
        [
            {"provider": "openai", "model": "x"},  # unsupported provider
            {"provider": "anthropic", "model": ""},  # empty model
            {"provider": "anthropic", "model": "m", "api_key_env": " "},
            [1, 2, 3],  # not an object
        ],
    )
    def test_bad_configs_rejected(self, tmp_path, payload):
        with pytest.raises(LlmConfigError):
            load_llm_config(write_config(tmp_path, payload))

    def test_corrupt_json_rejected(self, tmp_path):
        path = tmp_path / "llm.json"
        path.write_text("{nope")
        with pytest.raises(LlmConfigError):
            load_llm_config(path)

    def test_key_resolution(self):
        cfg = LlmConfig("anthropic", "m", "MY_KEY")
        assert resolve_api_key(cfg, environ={"MY_KEY": "sk-123"}) == "sk-123"
        with pytest.raises(LlmConfigError, match="MY_KEY"):
            resolve_api_key(cfg, environ={})
        with pytest.raises(LlmConfigError):
            resolve_api_key(cfg, environ={"MY_KEY": "   "})


class _Block:
    def __init__(self, type_, text=""):
        self.type = type_
        self.text = text


class _Usage:
    input_tokens = 11
    output_tokens = 7


class _FakeMessages:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome

        class R:
            content = [_Block("thinking"), _Block("text", "hi "), _Block("text", "there")]
            model = "claude-opus-5"
            stop_reason = "end_turn"
            usage = _Usage()

        return R()


class _FakeClient:
    def __init__(self, outcome=None):
        self.messages = _FakeMessages(outcome)


def make_adapter(outcome=None, monkeypatch=None):
    cfg = LlmConfig("anthropic", "claude-opus-5", "TEST_KEY")
    client = _FakeClient(outcome)
    import os

    os.environ["TEST_KEY"] = "sk-test"
    try:
        adapter = AnthropicAdapter(cfg, client_factory=lambda key: client)
    finally:
        os.environ.pop("TEST_KEY", None)
    return adapter, client


def request() -> LlmRequest:
    return LlmRequest(
        system_prompt="SYS",
        messages=(LlmMessage("user", "u1"), LlmMessage("assistant", "a1"),
                  LlmMessage("user", "u2")),
        model="claude-opus-5",
        max_tokens=300,
        metadata=(("scope", "PRIVATE"),),
    )


class TestAnthropicAdapter:
    def test_missing_key_fails_at_construction(self):
        cfg = LlmConfig("anthropic", "m", "DEFINITELY_UNSET_VAR_XYZ")
        with pytest.raises(LlmConfigError):
            AnthropicAdapter(cfg, client_factory=lambda key: _FakeClient())

    def test_payload_built_only_from_request_fields(self):
        adapter, client = make_adapter()
        response = adapter.complete(request())
        call = client.messages.calls[0]
        assert call == {
            "model": "claude-opus-5",
            "max_tokens": 300,
            "system": "SYS",
            "messages": [
                {"role": "user", "content": "u1"},
                {"role": "assistant", "content": "a1"},
                {"role": "user", "content": "u2"},
            ],
        }  # nothing beyond the frozen request's fields
        assert response.text == "hi there"
        assert response.input_tokens == 11 and response.output_tokens == 7

    def test_error_mapping(self):
        import anthropic
        import httpx

        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        conn_err = anthropic.APIConnectionError(request=req)
        adapter, _ = make_adapter(outcome=conn_err)
        with pytest.raises(LlmNetworkError):
            adapter.complete(request())

        status_err = anthropic.APIStatusError(
            "overloaded",
            response=httpx.Response(529, request=req),
            body={"error": {"message": "overloaded"}},
        )
        adapter, _ = make_adapter(outcome=status_err)
        with pytest.raises(LlmResponseError):
            adapter.complete(request())
