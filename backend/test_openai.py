from backend.azure_foundry import DEFAULT_FOUNDRY_DEPLOYMENT
from backend.openai_official import (
    DEFAULT_OPENAI_API_URL, DEFAULT_OPENAI_MODEL, OpenAIOfficialAdapter,
    build_openai_request_body, normalize_openai_api_url, openai_request_headers,
    resolve_openai_auth_mode, resolve_openai_model,
)
from backend.model_routing import (
    PROVIDER_FOUNDRY, PROVIDER_OPENAI, PROVIDER_SILICONFLOW, build_harness_setup,
    create_adapter, missing_runtime_credentials, resolve_max_output_tokens,
    resolve_routed_model, resolve_task_provider,
)
from integration.run_real_test import TYPES


assert DEFAULT_OPENAI_MODEL == "gpt-6-sol"
assert DEFAULT_OPENAI_API_URL == "https://api.openai.com/v1/chat/completions"
assert resolve_openai_model("planning", {}) == "gpt-6-sol"
assert resolve_openai_model("arbiter", {"OPENAI_ARBITER_MODEL": "gpt-6-sol-preview"}) == "gpt-6-sol-preview"
assert resolve_openai_model("review_plot", {"OPENAI_REVIEW_MODEL": "gpt-6-sol"}) == "gpt-6-sol"
assert resolve_openai_model("writing", {"OPENAI_WRITING_MODEL": "gpt-6-sol"}) == "gpt-6-sol"
assert resolve_openai_model(
    "memory_extraction",
    {"OPENAI_STRUCTURED_MODEL": "gpt-6-sol", "OPENAI_MEMORY_MODEL": "other-memory"},
) == "other-memory"


# Tentative split: Foundry writing/memory, OpenAI planning + reviews + arbiter.
split = {
    "WRITING_PROVIDER": "azure_foundry",
    "MEMORY_PROVIDER": "azure_foundry",
    "PLANNING_PROVIDER": "openai",
    "REVIEW_PROVIDER": "openai",
    "ARBITER_PROVIDER": "openai",
}
assert resolve_task_provider("writing", split) == PROVIDER_FOUNDRY
assert resolve_task_provider("memory_extraction", split) == PROVIDER_FOUNDRY
assert resolve_task_provider("planning", split) == PROVIDER_OPENAI
assert resolve_task_provider("review_world", split) == PROVIDER_OPENAI
assert resolve_task_provider("review_plot", split) == PROVIDER_OPENAI
assert resolve_task_provider("review_style", split) == PROVIDER_OPENAI
assert resolve_task_provider("arbiter", split) == PROVIDER_OPENAI
assert resolve_routed_model("planning", split) == DEFAULT_OPENAI_MODEL
assert resolve_routed_model("writing", split) == DEFAULT_FOUNDRY_DEPLOYMENT
assert resolve_task_provider("planning", {"PLANNING_PROVIDER": "openai_official"}) == PROVIDER_OPENAI
assert resolve_task_provider("arbiter", {"ARBITER_PROVIDER": "gpt"}) == PROVIDER_OPENAI
assert resolve_task_provider("writing", {}) == PROVIDER_SILICONFLOW
assert resolve_max_output_tokens(PROVIDER_OPENAI, split) == 16000


# Missing official key is listed; SiliconFlow is not required for this split.
assert "OPENAI_API_KEY" in missing_runtime_credentials(split, task_types=TYPES)
assert "SILICONFLOW_API_KEY" not in missing_runtime_credentials(split, task_types=TYPES)
assert missing_runtime_credentials(
    {
        **split,
        "OPENAI_API_KEY": "sk-placeholder-not-used",
        "AZURE_FOUNDRY_CLAUDE_ENDPOINT": "https://example-resource.services.ai.azure.com/anthropic",
        "AZURE_FOUNDRY_CLAUDE_API_KEY": "foundry-placeholder",
    },
    task_types=TYPES,
) == []
assert missing_runtime_credentials({}, task_types=TYPES) == ["SILICONFLOW_API_KEY"]


# Foundry project endpoint becomes OpenAI-compatible Chat Completions.
project = "https://example-resource.services.ai.azure.com/api/projects/example-project"
assert normalize_openai_api_url(project) == project + "/openai/v1/chat/completions"
assert normalize_openai_api_url(project + "/openai/v1") == project + "/openai/v1/chat/completions"
assert normalize_openai_api_url(project + "/openai/v1/chat/completions") == project + "/openai/v1/chat/completions"
assert resolve_openai_auth_mode(project) == "api_key"
azure_headers = openai_request_headers(project, "foundry-placeholder")
assert azure_headers["api-key"] == "foundry-placeholder"
assert "Authorization" not in azure_headers
official_headers = openai_request_headers(DEFAULT_OPENAI_API_URL, "sk-placeholder")
assert official_headers["Authorization"] == "Bearer sk-placeholder"
assert "api-key" not in official_headers


# Request body never contains a key.
secret = "sk-test-key-must-not-leak"
request = {
    "task_type": "planning",
    "contract_type": "ScenePlan",
    "model": "gpt-6-sol",
    "max_output_tokens": 2048,
    "input": {"brief": {"payload": {"premise": "推进"}}},
}
body = build_openai_request_body(request, default_model="unused")
assert body["model"] == "gpt-6-sol"
assert body["max_completion_tokens"] == 2048
assert "temperature" not in body
assert "max_tokens" not in body
assert build_openai_request_body(
    request, default_model="unused", environ={"OPENAI_TEMPERATURE": "0"}
)["temperature"] == 0.0
assert "messages" in body
assert secret not in str(body)
assert "Authorization" not in body
assert "api_key" not in body
assert "OPENAI_API_KEY" not in body

legacy = build_openai_request_body(
    request, default_model="unused", environ={"OPENAI_MAX_TOKENS_FIELD": "max_tokens"}
)
assert legacy["max_tokens"] == 2048
assert "max_completion_tokens" not in legacy


# Missing key fails before any network call.
try:
    OpenAIOfficialAdapter(environ={}).complete(request, 1)
except RuntimeError as error:
    assert str(error) == "OPENAI_API_KEY_MISSING"
else:
    raise AssertionError("missing official key was not rejected")


routes, adapters = build_harness_setup(TYPES, split)
assert routes["planning"].provider == PROVIDER_OPENAI
assert routes["planning"].model == "gpt-6-sol"
assert routes["arbiter"].provider == PROVIDER_OPENAI
assert routes["writing"].provider == PROVIDER_FOUNDRY
assert routes["memory_extraction"].provider == PROVIDER_FOUNDRY
assert isinstance(adapters[PROVIDER_OPENAI], OpenAIOfficialAdapter)
assert PROVIDER_SILICONFLOW not in adapters
assert isinstance(create_adapter(PROVIDER_OPENAI), OpenAIOfficialAdapter)

print("ok")
