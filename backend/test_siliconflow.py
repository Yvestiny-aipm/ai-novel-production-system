import os
from siliconflow import (DEFAULT_SILICONFLOW_MODEL, DEFAULT_TIMEOUT_SECONDS, SiliconFlowAdapter,
    TimeoutConfigError, build_request_body, json_mode_enabled, resolve_task_model, resolve_task_timeout)


old = os.environ.pop("SILICONFLOW_API_KEY", None)
try:
    try:
        SiliconFlowAdapter().complete({"input": {}}, 0)
    except RuntimeError as error:
        assert str(error) == "SILICONFLOW_API_KEY_MISSING"
    else:
        raise AssertionError("missing key was not rejected")
finally:
    if old is not None:
        os.environ["SILICONFLOW_API_KEY"] = old


# 7. Unconfigured environ keeps the current DeepSeek default.
assert DEFAULT_SILICONFLOW_MODEL == "deepseek-ai/DeepSeek-V3"
assert resolve_task_model("writing", {}) == DEFAULT_SILICONFLOW_MODEL
assert resolve_task_model("review_plot", {}) == DEFAULT_SILICONFLOW_MODEL
assert resolve_task_model("planning", {}, default="mock") == "mock"

# 4 / 5 / 6. Task, group, and default priority.
env = {
    "SILICONFLOW_DEFAULT_MODEL": "vendor/default",
    "SILICONFLOW_STRUCTURED_MODEL": "vendor/structured",
    "SILICONFLOW_WRITING_MODEL": "vendor/writing",
    "SILICONFLOW_REVIEW_MODEL": "vendor/review",
}
assert resolve_task_model("writing", env) == "vendor/writing"
assert resolve_task_model("review_world", env) == "vendor/review"
assert resolve_task_model("review_plot", env) == "vendor/review"
assert resolve_task_model("review_style", env) == "vendor/review"
assert resolve_task_model("planning", env) == "vendor/structured"
assert resolve_task_model("arbiter", env) == "vendor/structured"
assert resolve_task_model("memory_extraction", env) == "vendor/structured"
assert resolve_task_model("planning", {
    "SILICONFLOW_DEFAULT_MODEL": "vendor/default",
    "SILICONFLOW_STRUCTURED_MODEL": "vendor/structured",
    "SILICONFLOW_PLANNING_MODEL": "vendor/planning",
}) == "vendor/planning"
assert resolve_task_model("review_plot", {
    "SILICONFLOW_DEFAULT_MODEL": "vendor/default",
    "SILICONFLOW_STRUCTURED_MODEL": "vendor/structured",
}) == "vendor/structured"
assert resolve_task_model("writing", {"SILICONFLOW_DEFAULT_MODEL": "vendor/default"}) == "vendor/default"


# 1 / 2. Body.model follows the Harness request; adapter default is only a fallback.
request = {
    "task_type": "review_plot",
    "contract_type": "ReviewerResult",
    "model": "vendor/review",
    "max_output_tokens": 123,
    "input": {"draft": {}},
}
body = build_request_body(request, default_model="deepseek-ai/DeepSeek-V3", environ={})
assert body["model"] == "vendor/review"
assert body["max_tokens"] == 123
assert body["temperature"] == 0
assert "messages" in body
fallback = build_request_body({"contract_type": "ProseDraft", "input": {}}, default_model="adapter-default", environ={})
assert fallback["model"] == "adapter-default"
assert "response_format" not in body
assert "response_format" not in fallback
assert json_mode_enabled({}) is False
assert json_mode_enabled({"SILICONFLOW_JSON_MODE": "1"}) is True
enabled = build_request_body({**request, "json_mode": True}, default_model="deepseek-ai/DeepSeek-V3")
assert enabled["response_format"] == {"type": "json_object"}
env_enabled = build_request_body({"contract_type": "ScenePlan", "input": {}}, default_model="m",
                                 environ={"SILICONFLOW_JSON_MODE": "1"})
assert env_enabled["response_format"] == {"type": "json_object"}
assert "api_key" not in enabled
assert "Authorization" not in enabled


# Timeout routing: default, group, specific, and invalid values.
assert DEFAULT_TIMEOUT_SECONDS == 60
assert resolve_task_timeout("writing", {}) == 60
assert resolve_task_timeout("review_plot", {}) == 60
structured = {"SILICONFLOW_STRUCTURED_TIMEOUT_SECONDS": "180"}
assert resolve_task_timeout("review_plot", structured) == 180
assert resolve_task_timeout("planning", structured) == 180
assert resolve_task_timeout("arbiter", structured) == 180
assert resolve_task_timeout("memory_extraction", structured) == 180
assert resolve_task_timeout("writing", structured) == 60
assert resolve_task_timeout("review_plot", {
    "SILICONFLOW_STRUCTURED_TIMEOUT_SECONDS": "180",
    "SILICONFLOW_REVIEW_TIMEOUT_SECONDS": "90",
}) == 90
assert resolve_task_timeout("planning", {
    "SILICONFLOW_DEFAULT_TIMEOUT_SECONDS": "120",
    "SILICONFLOW_STRUCTURED_TIMEOUT_SECONDS": "180",
    "SILICONFLOW_PLANNING_TIMEOUT_SECONDS": "45",
}) == 45
assert resolve_task_timeout("writing", {"SILICONFLOW_DEFAULT_TIMEOUT_SECONDS": "120"}) == 120
for bad in ("0", "-1", "601", "abc", "", "NaN"):
    try:
        resolve_task_timeout("writing", {"SILICONFLOW_WRITING_TIMEOUT_SECONDS": bad})
    except TimeoutConfigError:
        pass
    else:
        raise AssertionError(f"invalid timeout {bad!r} was accepted")


# 12. API key never enters the request or body.
secret = "sk-test-key-must-not-leak"
os.environ["SILICONFLOW_API_KEY"] = secret
try:
    leaked = secret in str(request) or secret in str(body) or "api_key" in body or "Authorization" in body
    assert leaked is False
    assert "SILICONFLOW_API_KEY" not in body
    assert "api_key" not in request
finally:
    os.environ.pop("SILICONFLOW_API_KEY", None)
    if old is not None:
        os.environ["SILICONFLOW_API_KEY"] = old

print("ok")
