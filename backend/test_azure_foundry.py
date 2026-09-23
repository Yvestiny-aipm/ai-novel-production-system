import os

from backend.azure_foundry import (
    AzureFoundryAdapter, DEFAULT_FOUNDRY_DEPLOYMENT,
    build_foundry_kwargs, extract_text_content, finish_reason_from_stop,
    normalize_foundry_base_url, resolve_foundry_auth, resolve_foundry_thinking,
    split_system_and_messages,
)

EXAMPLE_FOUNDRY_ENDPOINT = "https://example-resource.services.ai.azure.com/anthropic"
from backend.siliconflow import ModelResponseParseError


class FakeBlock:
    def __init__(self, text, type="text"):
        self.type = type
        self.text = text


class FakeUsage:
    def __init__(self, input_tokens=3, output_tokens=5):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeMessage:
    def __init__(self, text, stop_reason="end_turn", extra_blocks=None):
        self.content = list(extra_blocks or []) + [FakeBlock(text)]
        self.stop_reason = stop_reason
        self.usage = FakeUsage()


class FakeClient:
    def __init__(self, message=None, error=None):
        self.calls = []
        self.messages = self
        self.message = message or FakeMessage(
            '{"contract_type":"ScenePlan","contract_version":"v1","payload":{"scene_goal":"x"}}'
        )
        self.error = error

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.message


# 1. SDK base_url stays at /anthropic; /v1/messages is stripped. Empty stays empty.
assert normalize_foundry_base_url(EXAMPLE_FOUNDRY_ENDPOINT + "/v1/messages") == EXAMPLE_FOUNDRY_ENDPOINT
assert normalize_foundry_base_url(EXAMPLE_FOUNDRY_ENDPOINT + "/") == EXAMPLE_FOUNDRY_ENDPOINT
assert normalize_foundry_base_url("") == ""


# 2. System prompt is split out; user messages stay in order.
system, messages = split_system_and_messages([
    {"role": "system", "content": "Return JSON"},
    {"role": "user", "content": '{"scene":1}'},
    {"role": "user", "content": "write the plan"},
])
assert system == "Return JSON"
assert messages == [
    {"role": "user", "content": '{"scene":1}'},
    {"role": "user", "content": "write the plan"},
]


# 3. Request kwargs never contain secrets; model follows Harness.
request = {
    "task_type": "planning",
    "contract_type": "ScenePlan",
    "model": "claude-opus-5",
    "max_output_tokens": 2048,
    "input": {"goal": "推进"},
}
kwargs = build_foundry_kwargs(request, default_model="unused-default")
assert kwargs["model"] == "claude-opus-5"
assert kwargs["max_tokens"] == 2048
assert "temperature" not in kwargs
assert kwargs["thinking"] == {"type": "disabled"}
assert kwargs["output_config"] == {"effort": "low"}
assert resolve_foundry_thinking("claude-opus-5") == {"type": "disabled"}
assert resolve_foundry_thinking("claude-opus-5-5-ay-cuizhiyuan") == {"type": "adaptive"}
assert build_foundry_kwargs(
    {**request, "model": "claude-opus-5-5"}, default_model="unused"
)["thinking"] == {"type": "adaptive"}
assert resolve_foundry_thinking("claude-opus-5-5", {"AZURE_FOUNDRY_THINKING": "disabled"}) == {
    "type": "disabled"
}
assert kwargs["system"]
assert kwargs["messages"][0]["role"] == "user"
assert "api_key" not in kwargs
assert "Authorization" not in kwargs
assert DEFAULT_FOUNDRY_DEPLOYMENT == "claude-opus-5"


# 4. Text blocks are joined; thinking blocks are ignored.
thinking = type("Think", (), {"type": "thinking", "text": "scratch"})()
assert extract_text_content(FakeMessage("{\"ok\":1}", extra_blocks=[thinking])) == "{\"ok\":1}"
assert finish_reason_from_stop("max_tokens") == "length"
assert finish_reason_from_stop("end_turn") == "end_turn"


# 5. Missing endpoint or API key fails before any network call.
old = os.environ.pop("AZURE_FOUNDRY_CLAUDE_API_KEY", None)
try:
    try:
        AzureFoundryAdapter(environ={}).complete({"contract_type": "ScenePlan", "input": {}}, 1)
    except RuntimeError as error:
        assert str(error) == "AZURE_FOUNDRY_ENDPOINT_MISSING"
    else:
        raise AssertionError("missing Foundry endpoint was not rejected")
    try:
        AzureFoundryAdapter(
            endpoint=EXAMPLE_FOUNDRY_ENDPOINT, environ={}
        ).complete({"contract_type": "ScenePlan", "input": {}}, 1)
    except RuntimeError as error:
        assert str(error) == "AZURE_FOUNDRY_API_KEY_MISSING"
    else:
        raise AssertionError("missing Foundry key was not rejected")
finally:
    if old is not None:
        os.environ["AZURE_FOUNDRY_CLAUDE_API_KEY"] = old


# 6. Injected client is used; parsed contract is returned; key never enters kwargs.
secret = "sk-foundry-must-not-leak"
os.environ["AZURE_FOUNDRY_CLAUDE_API_KEY"] = secret
try:
    client = FakeClient()
    adapter = AzureFoundryAdapter(client=client, environ={"AZURE_FOUNDRY_CLAUDE_API_KEY": secret})
    result = adapter.complete({
        "task_type": "planning",
        "contract_type": "ScenePlan",
        "model": "claude-opus-5",
        "input": {"goal": "推进"},
    }, 12)
    assert result["contract_type"] == "ScenePlan"
    assert result["payload"]["scene_goal"] == "x"
    assert client.calls[0]["model"] == "claude-opus-5"
    assert secret not in str(client.calls[0])
    assert "api_key" not in client.calls[0]
finally:
    os.environ.pop("AZURE_FOUNDRY_CLAUDE_API_KEY", None)
    if old is not None:
        os.environ["AZURE_FOUNDRY_CLAUDE_API_KEY"] = old


# 7. Truncated JSON is a technical parse error, not a content failure.
client = FakeClient(FakeMessage('{"contract_type":"ScenePlan","payload":{"scene_goal":"', stop_reason="max_tokens"))
try:
    AzureFoundryAdapter(client=client).complete({"contract_type": "ScenePlan", "input": {}}, 1)
except ModelResponseParseError as error:
    assert error.error_code == "MODEL_OUTPUT_TRUNCATED"
    assert error.finish_reason == "length"
    assert error.usage["output_tokens"] == 5
else:
    raise AssertionError("truncated Foundry JSON was accepted")


# 8. Auth mode: explicit entra does not require an API key at construction.
assert resolve_foundry_auth({"AZURE_FOUNDRY_AUTH": "entra"}) == "entra"
assert resolve_foundry_auth({}) == "api_key"

print("ok")
