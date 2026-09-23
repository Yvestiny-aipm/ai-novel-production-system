"""Official OpenAI Chat Completions adapter. Secrets stay in environment variables."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from backend.siliconflow import (
    ModelResponseParseError,
    STRUCTURED_TASKS,
    build_chat_messages,
    parse_contract_content,
    retry_memory_refusal,
)

PROVIDER_OPENAI = "openai"
DEFAULT_OPENAI_MODEL = "gpt-6-sol"
DEFAULT_OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_API_URL_ENV = "OPENAI_API_URL"
OPENAI_AUTH_ENV = "OPENAI_AUTH"
OPENAI_ORG_ENV = "OPENAI_ORG_ID"
OPENAI_MAX_OUTPUT_ENV = "OPENAI_MAX_OUTPUT_TOKENS"
OPENAI_TOKEN_FIELD_ENV = "OPENAI_MAX_TOKENS_FIELD"
DEFAULT_OPENAI_MAX_OUTPUT_TOKENS = 16000
AZURE_HOST_MARKERS = ("services.ai.azure.com", "openai.azure.com", "cognitiveservices.azure.com")
TASK_MODEL_ENV = {
    "writing": "OPENAI_WRITING_MODEL",
    "planning": "OPENAI_PLANNING_MODEL",
    "review_world": "OPENAI_REVIEW_MODEL",
    "review_plot": "OPENAI_REVIEW_MODEL",
    "review_style": "OPENAI_REVIEW_MODEL",
    "arbiter": "OPENAI_ARBITER_MODEL",
    "memory_extraction": "OPENAI_MEMORY_MODEL",
}


def _env_text(environ, name):
    if not name:
        return None
    value = environ.get(name)
    if isinstance(value, str):
        value = value.strip()
    return value or None


def resolve_openai_model(task_type, environ=None, *, default=None):
    env = environ if environ is not None else os.environ
    specific = _env_text(env, TASK_MODEL_ENV.get(task_type))
    if specific:
        return specific
    if task_type in STRUCTURED_TASKS:
        grouped = _env_text(env, "OPENAI_STRUCTURED_MODEL")
        if grouped:
            return grouped
    return (
        _env_text(env, "OPENAI_DEFAULT_MODEL")
        or default
        or DEFAULT_OPENAI_MODEL
    )


def is_azure_openai_url(url):
    host = (url or "").lower()
    return any(marker in host for marker in AZURE_HOST_MARKERS)


def normalize_openai_api_url(url):
    """Accept official Chat Completions URLs or a Foundry project base endpoint."""
    text = (url or "").strip()
    if not text:
        return DEFAULT_OPENAI_API_URL
    while text.endswith("/"):
        text = text[:-1]
    if text.endswith("/chat/completions"):
        return text
    if text.endswith("/openai/v1"):
        return text + "/chat/completions"
    if "/api/projects/" in text:
        return text + "/openai/v1/chat/completions"
    return text


def resolve_openai_auth_mode(url, environ=None):
    env = environ if environ is not None else os.environ
    explicit = (_env_text(env, OPENAI_AUTH_ENV) or "").lower()
    if explicit in {"api_key", "key"}:
        return "api_key"
    if explicit in {"bearer", "authorization"}:
        return "bearer"
    if is_azure_openai_url(url):
        return "api_key"
    return "bearer"


def openai_request_headers(url, key, environ=None):
    headers = {"Content-Type": "application/json"}
    if resolve_openai_auth_mode(url, environ) == "api_key":
        headers["api-key"] = key
        return headers
    headers["Authorization"] = "Bearer " + key
    org = _env_text(environ if environ is not None else os.environ, OPENAI_ORG_ENV)
    if org:
        headers["OpenAI-Organization"] = org
    return headers


def resolve_openai_token_field(environ=None):
    env = environ if environ is not None else os.environ
    field = (_env_text(env, OPENAI_TOKEN_FIELD_ENV) or "max_completion_tokens").strip()
    if field not in {"max_tokens", "max_completion_tokens"}:
        raise ValueError(f"UNKNOWN_OPENAI_MAX_TOKENS_FIELD:{field}")
    return field


def build_openai_request_body(request, default_model=None, *, environ=None):
    """OpenAI Chat Completions body. Never include secrets."""
    env = environ if environ is not None else os.environ
    field = resolve_openai_token_field(env)
    body = {
        "model": request.get("model") or default_model or DEFAULT_OPENAI_MODEL,
        "messages": build_chat_messages(request),
        field: request.get("max_output_tokens", 4096),
    }
    # GPT-6 Sol only accepts the default temperature (1). Omit unless explicitly set.
    temperature = _env_text(env, "OPENAI_TEMPERATURE")
    if temperature is not None:
        body["temperature"] = float(temperature)
    return body


class OpenAIOfficialAdapter:
    def __init__(self, *, api_url=None, environ=None, model=None, timeout=60):
        self.environ = environ if environ is not None else os.environ
        self.api_url = normalize_openai_api_url(
            api_url or _env_text(self.environ, OPENAI_API_URL_ENV) or DEFAULT_OPENAI_API_URL
        )
        self.model = model or resolve_openai_model("planning", self.environ)
        self.timeout = timeout

    def complete(self, request, timeout_seconds):
        key = _env_text(self.environ, OPENAI_API_KEY_ENV)
        if not key:
            raise RuntimeError("OPENAI_API_KEY_MISSING")
        body = build_openai_request_body(request, default_model=self.model, environ=self.environ)
        headers = openai_request_headers(self.api_url, key, self.environ)
        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds or self.timeout) as res:
                result = json.loads(res.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"HTTP Error {error.code}: {detail}") from error
        if result.get("error"):
            raise RuntimeError(result["error"])
        if result.get("contract"):
            return result["contract"]
        choice = (result.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        finish_reason = choice.get("finish_reason")
        usage = result.get("usage")
        refusal_reason = message.get("refusal")
        try:
            if finish_reason == "refusal" or isinstance(content, str):
                return parse_contract_content(
                    content if isinstance(content, str) else "",
                    finish_reason=finish_reason, usage=usage,
                    expected=request.get("contract_type"),
                    refusal_reason=refusal_reason,
                )
        except ModelResponseParseError as error:
            return retry_memory_refusal(self, error, request, timeout_seconds)
        return result
