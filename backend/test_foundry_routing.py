from backend.azure_foundry import DEFAULT_FOUNDRY_DEPLOYMENT
from backend.model_routing import (
    DEFAULT_MAX_OUTPUT_TOKENS, FOUNDRY_MAX_OUTPUT_TOKENS, PROVIDER_FOUNDRY,
    PROVIDER_SILICONFLOW, build_harness_setup, create_adapter,
    missing_runtime_credentials, resolve_max_output_tokens, resolve_routed_model,
    resolve_task_provider,
)
from backend.siliconflow import DEFAULT_SILICONFLOW_MODEL
from integration.run_real_test import TYPES


# 1. Default provider stays siliconflow so existing real tests do not change.
for role in TYPES:
    assert resolve_task_provider(role, {}) == PROVIDER_SILICONFLOW
    assert resolve_routed_model(role, {}) == DEFAULT_SILICONFLOW_MODEL


# 2. Structured tasks can move to Foundry while writing stays on SiliconFlow.
env = {"STRUCTURED_PROVIDER": "azure_foundry"}
assert resolve_task_provider("writing", env) == PROVIDER_SILICONFLOW
assert resolve_task_provider("planning", env) == PROVIDER_FOUNDRY
assert resolve_task_provider("review_plot", env) == PROVIDER_FOUNDRY
assert resolve_task_provider("arbiter", env) == PROVIDER_FOUNDRY
assert resolve_task_provider("memory_extraction", env) == PROVIDER_FOUNDRY
assert resolve_routed_model("writing", env) == DEFAULT_SILICONFLOW_MODEL
assert resolve_routed_model("planning", env) == DEFAULT_FOUNDRY_DEPLOYMENT
assert resolve_routed_model("review_style", env) == DEFAULT_FOUNDRY_DEPLOYMENT


# 3. Task and group Foundry model names override the deployment default.
foundry_env = {
    "STRUCTURED_PROVIDER": "foundry",
    "AZURE_FOUNDRY_STRUCTURED_MODEL": "claude-opus-5-structured",
    "AZURE_FOUNDRY_REVIEW_MODEL": "claude-opus-5-review",
    "AZURE_FOUNDRY_WRITING_MODEL": "unused-when-writing-stays",
    "SILICONFLOW_WRITING_MODEL": "vendor/writing",
}
assert resolve_routed_model("review_world", foundry_env) == "claude-opus-5-review"
assert resolve_routed_model("planning", foundry_env) == "claude-opus-5-structured"
assert resolve_routed_model("writing", foundry_env) == "vendor/writing"


# 4. All-Foundry routing uses the deployment name unless overridden.
all_foundry = {"MODEL_PROVIDER": "azure_foundry", "AZURE_FOUNDRY_CLAUDE_DEPLOYMENT": "claude-opus-5-ay-cuizhiyuan"}
assert resolve_task_provider("writing", all_foundry) == PROVIDER_FOUNDRY
assert resolve_routed_model("writing", all_foundry) == "claude-opus-5-ay-cuizhiyuan"


# 5. Runtime credential gate: Foundry-only accepts entra; mixed still needs SiliconFlow.
assert missing_runtime_credentials({}, task_types=TYPES) == ["SILICONFLOW_API_KEY"]
assert missing_runtime_credentials(
    {"MODEL_PROVIDER": "azure_foundry"}, task_types=TYPES
) == ["AZURE_FOUNDRY_CLAUDE_API_KEY or AZURE_FOUNDRY_AUTH=entra"]
assert missing_runtime_credentials(
    {"MODEL_PROVIDER": "azure_foundry", "AZURE_FOUNDRY_AUTH": "entra"},
    task_types=TYPES,
) == []
assert missing_runtime_credentials(
    {"STRUCTURED_PROVIDER": "azure_foundry", "AZURE_FOUNDRY_CLAUDE_API_KEY": "key"},
    task_types=TYPES,
) == ["SILICONFLOW_API_KEY"]
assert missing_runtime_credentials(
    {"STRUCTURED_PROVIDER": "azure_foundry", "AZURE_FOUNDRY_CLAUDE_API_KEY": "key",
     "SILICONFLOW_API_KEY": "sf"},
    task_types=TYPES,
) == []


# 6. Harness setup builds mixed adapters; mock path stays single-provider.
class Dummy:
    pass


dummy = Dummy()
routes, adapters = build_harness_setup(
    TYPES, {"STRUCTURED_PROVIDER": "azure_foundry", "SILICONFLOW_WRITING_MODEL": "vendor/writing"},
    siliconflow_adapter=dummy,
)
assert set(adapters) == {PROVIDER_SILICONFLOW, PROVIDER_FOUNDRY}
assert adapters[PROVIDER_SILICONFLOW] is dummy
assert routes["writing"].provider == PROVIDER_SILICONFLOW
assert routes["writing"].model == "vendor/writing"
assert routes["planning"].provider == PROVIDER_FOUNDRY
assert routes["planning"].model == DEFAULT_FOUNDRY_DEPLOYMENT
assert routes["planning"].max_output_tokens == FOUNDRY_MAX_OUTPUT_TOKENS
assert routes["writing"].max_output_tokens == DEFAULT_MAX_OUTPUT_TOKENS
assert routes["review_plot"].provider == PROVIDER_FOUNDRY
assert resolve_max_output_tokens(PROVIDER_FOUNDRY, {"AZURE_FOUNDRY_MAX_OUTPUT_TOKENS": "8000"}) == 8000

mock_routes, mock_adapters = build_harness_setup(
    TYPES, {"STRUCTURED_PROVIDER": "azure_foundry"}, mock=True, siliconflow_adapter=dummy
)
assert list(mock_adapters) == ["mock"]
assert mock_adapters["mock"] is dummy
assert {profile.provider for profile in mock_routes.values()} == {"mock"}
assert mock_routes["planning"].model == "mock"


# 7. create_adapter rejects unknown providers and does not invent SiliconFlow by default.
try:
    create_adapter("unknown")
except ValueError as error:
    assert str(error) == "UNKNOWN_PROVIDER:unknown"
else:
    raise AssertionError("unknown provider was accepted")

print("ok")
