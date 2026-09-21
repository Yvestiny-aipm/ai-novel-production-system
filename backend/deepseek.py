"""Official DeepSeek Chat Completions adapter. Secrets stay in environment variables."""
from __future__ import annotations

import json
import os
import urllib.request

from backend.siliconflow import (ModelResponseParseError, build_chat_messages,
    parse_contract_content, retry_memory_refusal)

PROVIDER_DEEPSEEK = "deepseek"
DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_API_KEY_ENV = "DEEPSEEK_API_KEY"
DEEPSEEK_API_URL_ENV = "DEEPSEEK_API_URL"
DEEPSEEK_WRITING_MODEL_ENV = "DEEPSEEK_WRITING_MODEL"


def _env_text(environ, name):
    if not name:
        return None
    value = environ.get(name)
    if isinstance(value, str):
        value = value.strip()
    return value or None


def resolve_deepseek_model(task_type, environ=None, *, default=None):
    env = environ if environ is not None else os.environ
    if task_type == "writing":
        return _env_text(env, DEEPSEEK_WRITING_MODEL_ENV) or default or DEFAULT_DEEPSEEK_MODEL
    return (
        _env_text(env, "DEEPSEEK_DEFAULT_MODEL")
        or _env_text(env, DEEPSEEK_WRITING_MODEL_ENV)
        or default
        or DEFAULT_DEEPSEEK_MODEL
    )


def build_deepseek_request_body(request, default_model=None):
    """OpenAI-compatible body. Official thinking defaults to enabled; disable it."""
    return {
        "model": request.get("model") or default_model or DEFAULT_DEEPSEEK_MODEL,
        "messages": build_chat_messages(request),
        "max_tokens": request.get("max_output_tokens", 4096),
        "temperature": 0,
        "thinking": {"type": "disabled"},
    }


class DeepSeekOfficialAdapter:
    def __init__(self, *, api_url=None, environ=None, model=None, timeout=60):
        self.environ = environ if environ is not None else os.environ
        self.api_url = api_url or _env_text(self.environ, DEEPSEEK_API_URL_ENV) or DEFAULT_DEEPSEEK_API_URL
        self.model = model or resolve_deepseek_model("writing", self.environ)
        self.timeout = timeout

    def complete(self, request, timeout_seconds):
        key = _env_text(self.environ, DEEPSEEK_API_KEY_ENV)
        if not key:
            raise RuntimeError("DEEPSEEK_API_KEY_MISSING")
        body = build_deepseek_request_body(request, default_model=self.model)
        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout_seconds or self.timeout) as res:
            result = json.loads(res.read())
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
