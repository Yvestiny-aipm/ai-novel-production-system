from backend.azure_foundry import DEFAULT_FOUNDRY_DEPLOYMENT
from backend.deepseek import (
    DEFAULT_DEEPSEEK_API_URL, DEFAULT_DEEPSEEK_MODEL, DeepSeekOfficialAdapter,
    build_deepseek_request_body, resolve_deepseek_model,
)
from backend.model_routing import (
    PROVIDER_DEEPSEEK, PROVIDER_FOUNDRY, PROVIDER_SILICONFLOW, build_harness_setup,
    create_adapter, missing_runtime_credentials, resolve_routed_model, resolve_task_provider,
)
from integration.run_real_test import TYPES


# Default writing model and URL stay official flash, not SiliconFlow V3.
assert DEFAULT_DEEPSEEK_MODEL == "deepseek-flash"
assert DEFAULT_DEEPSEEK_API_URL == "https://api.deepseek.com/chat/completions"
assert resolve_deepseek_model("writing", {}) == "deepseek-flash"
assert resolve_deepseek_model("writing", {"DEEPSEEK_WRITING_MODEL": "deepseek-chat"}) == "deepseek-chat"


# WRITING_PROVIDER=deepseek routes writing only; Foundry still owns structured tasks.
mixed = {
    "WRITING_PROVIDER": "deepseek",
    "STRUCTURED_PROVIDER": "azure_foundry",
}
assert resolve_task_provider("writing", mixed) == PROVIDER_DEEPSEEK
assert resolve_routed_model("writing", mixed) == "deepseek-flash"
assert resolve_task_provider("planning", mixed) == PROVIDER_FOUNDRY
assert resolve_task_provider("review_plot", mixed) == PROVIDER_FOUNDRY
assert resolve_task_provider("arbiter", mixed) == PROVIDER_FOUNDRY
assert resolve_routed_model("planning", mixed) == DEFAULT_FOUNDRY_DEPLOYMENT
assert resolve_task_provider("writing", {"WRITING_PROVIDER": "deepseek_official"}) == PROVIDER_DEEPSEEK
assert resolve_task_provider("writing", {}) == PROVIDER_SILICONFLOW


# Missing official key is listed; mixed Foundry + official writing does not need SiliconFlow.
assert "DEEPSEEK_API_KEY" in missing_runtime_credentials(mixed, task_types=TYPES)
assert "SILICONFLOW_API_KEY" not in missing_runtime_credentials(mixed, task_types=TYPES)
assert missing_runtime_credentials(
    {
        "WRITING_PROVIDER": "deepseek",
        "STRUCTURED_PROVIDER": "azure_foundry",
        "DEEPSEEK_API_KEY": "sk-placeholder-not-used",
        "AZURE_FOUNDRY_CLAUDE_ENDPOINT": "https://example-resource.services.ai.azure.com/anthropic",
        "AZURE_FOUNDRY_CLAUDE_API_KEY": "foundry-placeholder",
    },
    task_types=TYPES,
) == []
assert missing_runtime_credentials({}, task_types=TYPES) == ["SILICONFLOW_API_KEY"]


# Request body disables thinking and never contains a key.
secret = "sk-test-key-must-not-leak"
request = {
    "task_type": "writing",
    "contract_type": "ProseDraft",
    "model": "deepseek-flash",
    "max_output_tokens": 2048,
    "input": {"scene_plan": {"payload": {"scene_goal": "推进"}}},
}
body = build_deepseek_request_body(request, default_model="unused")
assert body["model"] == "deepseek-flash"
assert body["thinking"] == {"type": "disabled"}
assert body["max_tokens"] == 2048
assert "messages" in body
assert secret not in str(body)
assert "Authorization" not in body
assert "api_key" not in body
assert "DEEPSEEK_API_KEY" not in body


# Missing key fails before any network call.
try:
    DeepSeekOfficialAdapter(environ={}).complete(request, 1)
except RuntimeError as error:
    assert str(error) == "DEEPSEEK_API_KEY_MISSING"
else:
    raise AssertionError("missing official key was not rejected")


routes, adapters = build_harness_setup(TYPES, mixed)
assert routes["writing"].provider == PROVIDER_DEEPSEEK
assert routes["writing"].model == "deepseek-flash"
assert routes["planning"].provider == PROVIDER_FOUNDRY
assert isinstance(adapters[PROVIDER_DEEPSEEK], DeepSeekOfficialAdapter)
assert PROVIDER_SILICONFLOW not in adapters
assert isinstance(create_adapter(PROVIDER_DEEPSEEK), DeepSeekOfficialAdapter)

print("ok")
