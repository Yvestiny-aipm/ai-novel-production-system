"""Resolve provider, model, and adapters for each agent task."""
from __future__ import annotations

import os

from backend.azure_foundry import AzureFoundryAdapter, foundry_credentials_configured, resolve_foundry_model
from backend.harness import ModelProfile
from backend.siliconflow import (
    DEFAULT_SILICONFLOW_MODEL,
    STRUCTURED_TASKS,
    SiliconFlowAdapter,
    resolve_task_model,
    resolve_task_timeout,
)

PROVIDER_SILICONFLOW = "siliconflow"
PROVIDER_FOUNDRY = "azure_foundry"
DEFAULT_MAX_OUTPUT_TOKENS = 5000
FOUNDRY_MAX_OUTPUT_TOKENS = 16000
PROVIDER_ALIASES = {
    "foundry": PROVIDER_FOUNDRY,
    "azure": PROVIDER_FOUNDRY,
    "azure_foundry": PROVIDER_FOUNDRY,
    "siliconflow": PROVIDER_SILICONFLOW,
}
TASK_PROVIDER_ENV = {
    "writing": "WRITING_PROVIDER",
    "planning": "PLANNING_PROVIDER",
    "review_world": "REVIEW_PROVIDER",
    "review_plot": "REVIEW_PROVIDER",
    "review_style": "REVIEW_PROVIDER",
    "arbiter": "ARBITER_PROVIDER",
    "memory_extraction": "MEMORY_PROVIDER",
}


def _env_text(environ, name):
    if not name:
        return None
    value = environ.get(name)
    if isinstance(value, str):
        value = value.strip()
    return value or None


def normalize_provider(value, *, default=PROVIDER_SILICONFLOW):
    if not value:
        return default
    key = str(value).strip().lower()
    if key not in PROVIDER_ALIASES:
        raise ValueError(f"UNKNOWN_PROVIDER:{value}")
    return PROVIDER_ALIASES[key]


def resolve_task_provider(task_type, environ=None, *, default=PROVIDER_SILICONFLOW):
    env = environ if environ is not None else os.environ
    specific = _env_text(env, TASK_PROVIDER_ENV.get(task_type))
    if specific:
        return normalize_provider(specific)
    if task_type in STRUCTURED_TASKS:
        grouped = _env_text(env, "STRUCTURED_PROVIDER")
        if grouped:
            return normalize_provider(grouped)
    return normalize_provider(_env_text(env, "MODEL_PROVIDER") or default)


def resolve_routed_model(task_type, environ=None, *, default=None, provider=None):
    env = environ if environ is not None else os.environ
    chosen = provider or resolve_task_provider(task_type, env)
    if chosen == PROVIDER_FOUNDRY:
        return resolve_foundry_model(task_type, env, default=default)
    return resolve_task_model(task_type, env, default=default or DEFAULT_SILICONFLOW_MODEL)


def resolve_max_output_tokens(provider, environ=None):
    env = environ if environ is not None else os.environ
    if provider == PROVIDER_FOUNDRY:
        configured = _env_text(env, "AZURE_FOUNDRY_MAX_OUTPUT_TOKENS")
        if configured:
            return int(configured)
        return FOUNDRY_MAX_OUTPUT_TOKENS
    return DEFAULT_MAX_OUTPUT_TOKENS


def create_adapter(provider, *, siliconflow_adapter=None, environ=None):
    if provider == PROVIDER_SILICONFLOW:
        return siliconflow_adapter or SiliconFlowAdapter()
    if provider == PROVIDER_FOUNDRY:
        return AzureFoundryAdapter(environ=environ)
    raise ValueError(f"UNKNOWN_PROVIDER:{provider}")


def missing_runtime_credentials(environ=None, *, task_types=None):
    env = environ if environ is not None else os.environ
    roles = task_types or tuple(TASK_PROVIDER_ENV)
    providers = {resolve_task_provider(role, env) for role in roles}
    missing = []
    if PROVIDER_SILICONFLOW in providers and not _env_text(env, "SILICONFLOW_API_KEY"):
        missing.append("SILICONFLOW_API_KEY")
    if PROVIDER_FOUNDRY in providers and not foundry_credentials_configured(env):
        missing.append("AZURE_FOUNDRY_CLAUDE_API_KEY or AZURE_FOUNDRY_AUTH=entra")
    return missing


def build_harness_setup(
    task_types,
    environ,
    *,
    mock=False,
    siliconflow_adapter=None,
    timeout_environ=None,
    prompt_versions=None,
):
    timeout_env = timeout_environ if timeout_environ is not None else environ
    versions = prompt_versions or {}
    routes = {}
    adapters = {}
    if mock:
        adapters["mock"] = siliconflow_adapter
        for role in task_types:
            routes[role] = ModelProfile(
                "mock",
                resolve_task_model(role, environ, default="mock"),
                timeout_seconds=resolve_task_timeout(role, timeout_env),
                technical_retries=0,
                max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
                prompt_version=versions.get(role, "v1"),
            )
        return routes, adapters
    for role in task_types:
        provider = resolve_task_provider(role, environ)
        routes[role] = ModelProfile(
            provider,
            resolve_routed_model(role, environ, provider=provider),
            timeout_seconds=resolve_task_timeout(role, timeout_env),
            technical_retries=0,
            max_output_tokens=resolve_max_output_tokens(provider, environ),
            prompt_version=versions.get(role, "v1"),
        )
        if provider not in adapters:
            adapters[provider] = create_adapter(
                provider, siliconflow_adapter=siliconflow_adapter, environ=environ
            )
    return routes, adapters
