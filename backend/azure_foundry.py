"""Azure Foundry Claude adapter. Secrets stay in environment variables."""
from __future__ import annotations

import os

from backend.siliconflow import build_chat_messages, parse_contract_content

DEFAULT_FOUNDRY_DEPLOYMENT = "claude-opus-5"
DEFAULT_FOUNDRY_TOKEN_SCOPE = "https://ai.azure.com/.default"
FOUNDRY_API_KEY_ENV = "AZURE_FOUNDRY_CLAUDE_API_KEY"
FOUNDRY_ENDPOINT_ENV = "AZURE_FOUNDRY_CLAUDE_ENDPOINT"
FOUNDRY_DEPLOYMENT_ENV = "AZURE_FOUNDRY_CLAUDE_DEPLOYMENT"
FOUNDRY_AUTH_ENV = "AZURE_FOUNDRY_AUTH"
FOUNDRY_TOKEN_SCOPE_ENV = "AZURE_FOUNDRY_TOKEN_SCOPE"

TASK_MODEL_ENV = {
    "writing": "AZURE_FOUNDRY_WRITING_MODEL",
    "planning": "AZURE_FOUNDRY_PLANNING_MODEL",
    "review_world": "AZURE_FOUNDRY_REVIEW_MODEL",
    "review_plot": "AZURE_FOUNDRY_REVIEW_MODEL",
    "review_style": "AZURE_FOUNDRY_REVIEW_MODEL",
    "arbiter": "AZURE_FOUNDRY_ARBITER_MODEL",
    "memory_extraction": "AZURE_FOUNDRY_MEMORY_MODEL",
}


def _env_text(environ, name):
    if not name:
        return None
    value = environ.get(name)
    if isinstance(value, str):
        value = value.strip()
    return value or None


def normalize_foundry_base_url(url):
    text = (url or "").strip()
    if not text:
        return ""
    while text.endswith("/"):
        text = text[:-1]
    if text.endswith("/v1/messages"):
        text = text[: -len("/v1/messages")]
    elif text.endswith("/v1"):
        text = text[: -len("/v1")]
    return text


def resolve_foundry_auth(environ=None):
    env = environ if environ is not None else os.environ
    explicit = str(env.get(FOUNDRY_AUTH_ENV) or "").strip().lower()
    if explicit in {"entra", "azure_ad", "ad"}:
        return "entra"
    if explicit in {"api_key", "key"}:
        return "api_key"
    return "api_key"


def foundry_credentials_configured(environ=None):
    env = environ if environ is not None else os.environ
    if resolve_foundry_auth(env) == "entra":
        return True
    return bool(_env_text(env, FOUNDRY_API_KEY_ENV) or os.getenv(FOUNDRY_API_KEY_ENV))


def resolve_foundry_model(task_type, environ=None, *, default=None):
    from backend.siliconflow import STRUCTURED_TASKS

    env = environ if environ is not None else os.environ
    specific = _env_text(env, TASK_MODEL_ENV.get(task_type))
    if specific:
        return specific
    if task_type in STRUCTURED_TASKS:
        grouped = _env_text(env, "AZURE_FOUNDRY_STRUCTURED_MODEL")
        if grouped:
            return grouped
    return (
        _env_text(env, "AZURE_FOUNDRY_DEFAULT_MODEL")
        or _env_text(env, FOUNDRY_DEPLOYMENT_ENV)
        or default
        or DEFAULT_FOUNDRY_DEPLOYMENT
    )


def split_system_and_messages(chat_messages):
    system_parts = []
    messages = []
    for item in chat_messages or []:
        role = item.get("role")
        content = item.get("content")
        if role == "system":
            if content:
                system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            raise ValueError(f"UNSUPPORTED_CHAT_ROLE:{role}")
        messages.append({"role": role, "content": content})
    return "\n\n".join(system_parts), messages


def build_foundry_kwargs(request, default_model=None):
    system, messages = split_system_and_messages(build_chat_messages(request))
    kwargs = {
        "model": request.get("model") or default_model or DEFAULT_FOUNDRY_DEPLOYMENT,
        "messages": messages,
        "max_tokens": request.get("max_output_tokens", 4096),
        # Opus 5 thinks by default and can spend the whole max_tokens budget
        # on thinking blocks, leaving empty visible JSON.
        "thinking": {"type": "disabled"},
        "output_config": {"effort": "low"},
    }
    if system:
        kwargs["system"] = system
    return kwargs


def extract_text_content(message):
    blocks = getattr(message, "content", None)
    if blocks is None and isinstance(message, dict):
        blocks = message.get("content")
    if isinstance(blocks, str):
        return blocks
    texts = []
    for block in blocks or []:
        if isinstance(block, str):
            texts.append(block)
            continue
        btype = getattr(block, "type", None)
        if btype is None and isinstance(block, dict):
            btype = block.get("type")
        if btype not in (None, "text"):
            continue
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            texts.append(text)
    return "".join(texts)


def usage_from_message(message):
    usage = getattr(message, "usage", None)
    if usage is None and isinstance(message, dict):
        usage = message.get("usage")
    if usage is None:
        return None
    if isinstance(usage, dict):
        return {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }


def finish_reason_from_stop(stop_reason):
    if stop_reason == "max_tokens":
        return "length"
    return stop_reason


def create_foundry_client(*, base_url, timeout, api_key=None, token_provider=None):
    try:
        from anthropic import AnthropicFoundry
    except ImportError as error:
        raise RuntimeError("ANTHROPIC_SDK_MISSING") from error
    kwargs = {"base_url": base_url, "timeout": timeout}
    if token_provider is not None:
        kwargs["azure_ad_token_provider"] = token_provider
    elif api_key:
        kwargs["api_key"] = api_key
    else:
        raise RuntimeError("AZURE_FOUNDRY_API_KEY_MISSING")
    return AnthropicFoundry(**kwargs)


class AzureFoundryAdapter:
    def __init__(
        self,
        *,
        endpoint=None,
        api_key_env=FOUNDRY_API_KEY_ENV,
        model=None,
        timeout=60,
        environ=None,
        client=None,
        client_factory=None,
    ):
        self.environ = environ if environ is not None else os.environ
        self.api_key_env = api_key_env
        self.base_url = normalize_foundry_base_url(
            endpoint or _env_text(self.environ, FOUNDRY_ENDPOINT_ENV)
        )
        self.model = (
            model
            or _env_text(self.environ, FOUNDRY_DEPLOYMENT_ENV)
            or DEFAULT_FOUNDRY_DEPLOYMENT
        )
        self.timeout = timeout
        self.auth_mode = resolve_foundry_auth(self.environ)
        self._client = client
        self._client_timeout = None if client is None else timeout
        self._client_factory = client_factory

    def _secret(self):
        return _env_text(self.environ, self.api_key_env) or _env_text(os.environ, self.api_key_env)

    def _token_provider(self):
        try:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        except ImportError as error:
            raise RuntimeError("AZURE_IDENTITY_SDK_MISSING") from error
        scope = _env_text(self.environ, FOUNDRY_TOKEN_SCOPE_ENV) or DEFAULT_FOUNDRY_TOKEN_SCOPE
        return get_bearer_token_provider(DefaultAzureCredential(), scope)

    def _ensure_client(self, timeout_seconds):
        timeout = timeout_seconds or self.timeout
        if self._client is not None and (self._client_factory is None or self._client_timeout == timeout):
            return self._client
        if not self.base_url:
            raise RuntimeError("AZURE_FOUNDRY_ENDPOINT_MISSING")
        factory = self._client_factory or create_foundry_client
        if self.auth_mode == "entra":
            client = factory(base_url=self.base_url, timeout=timeout, token_provider=self._token_provider())
        else:
            key = self._secret()
            if not key:
                raise RuntimeError("AZURE_FOUNDRY_API_KEY_MISSING")
            client = factory(base_url=self.base_url, timeout=timeout, api_key=key)
        self._client = client
        self._client_timeout = timeout
        return client

    def complete(self, request, timeout_seconds):
        client = self._ensure_client(timeout_seconds)
        kwargs = build_foundry_kwargs(request, default_model=self.model)
        message = client.messages.create(**kwargs)
        if isinstance(message, dict) and message.get("contract"):
            return message["contract"]
        content = extract_text_content(message)
        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason is None and isinstance(message, dict):
            stop_reason = message.get("stop_reason")
        if isinstance(content, str):
            return parse_contract_content(
                content,
                finish_reason=finish_reason_from_stop(stop_reason),
                usage=usage_from_message(message),
                expected=request.get("contract_type"),
            )
        return message
