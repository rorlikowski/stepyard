"""Built-in LLM node with pluggable providers and optional structured output."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Protocol, cast

from pydantic import BaseModel, Field, ValidationError, create_model

from stepyard.sdk.node import NodeContext, node

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

_SUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "type",
        "properties",
        "required",
        "items",
        "enum",
        "description",
        "title",
        "$defs",
        "$ref",
        "additionalProperties",
    }
)


@dataclass
class LLMRequest:
    prompt: str
    model: str
    system_prompt: str | None
    api_key: str
    base_url: str
    max_tokens: int
    temperature: float | None
    timeout: float
    output_schema: dict[str, Any] | None
    schema_name: str
    output_validator: type[BaseModel] | None = None


class LLMProvider(Protocol):
    name: str
    api_key_env: tuple[str, ...]
    default_base_url: str
    api_label: str

    def build_request(self, req: LLMRequest) -> tuple[str, dict[str, str], dict[str, Any]]: ...

    def parse_response(self, data: dict[str, Any], req: LLMRequest) -> Any: ...


def _unsupported_schema_keys(schema: dict[str, Any], path: str = "") -> list[str]:
    unsupported: list[str] = []
    for key, value in schema.items():
        if key not in _SUPPORTED_SCHEMA_KEYS:
            unsupported.append(f"{path}.{key}" if path else key)
        if isinstance(value, dict):
            unsupported.extend(_unsupported_schema_keys(value, f"{path}.{key}" if path else key))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    unsupported.extend(
                        _unsupported_schema_keys(
                            item, f"{path}.{key}[{idx}]" if path else f"{key}[{idx}]"
                        )
                    )
    return unsupported


def _enum_type(name: str, values: list[Any]) -> Any:
    members = {str(value).replace(" ", "_").replace("-", "_"): value for value in values}
    value_type: type[Any] = type(values[0]) if values else str
    return Enum(name, members, type=value_type)


def _json_schema_to_type(schema: dict[str, Any], *, path: str, model_name: str) -> Any:
    unsupported = _unsupported_schema_keys(schema, path)
    if unsupported:
        raise ValueError(
            "Unsupported JSON Schema keyword(s): "
            + ", ".join(unsupported)
            + ". Supported subset: object/array/primitive types, properties, required, items, enum."
        )

    if "enum" in schema:
        enum_values = schema["enum"]
        if not enum_values:
            raise ValueError(f"Schema enum at '{path}' must not be empty.")
        safe_name = re.sub(r"[^0-9a-zA-Z_]", "_", path or model_name) or "Enum"
        return _enum_type(f"{model_name}_{safe_name}", enum_values)

    schema_type = schema.get("type")
    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        items = schema.get("items")
        if not isinstance(items, dict):
            raise ValueError(f"Schema array at '{path}' requires an 'items' object.")
        item_type: Any = _json_schema_to_type(items, path=f"{path}[]", model_name=model_name)
        return list[item_type]
    if schema_type == "object":
        return _build_output_validator(schema, name=model_name)

    raise ValueError(
        f"Unsupported or missing schema type at '{path}'. "
        "Use one of: string, integer, number, boolean, array, object."
    )


def _build_output_validator(
    schema: dict[str, Any], name: str = "StructuredOutput"
) -> type[BaseModel]:
    if schema.get("type") != "object":
        raise ValueError("Structured output schema must have top-level type: object.")

    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("Structured output schema must define a non-empty 'properties' mapping.")

    required = set(schema.get("required") or [])
    fields: dict[str, tuple[Any, Any]] = {}
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            raise ValueError(f"Schema property '{prop_name}' must be an object.")
        field_type = _json_schema_to_type(
            prop_schema,
            path=prop_name,
            model_name=f"{name}_{prop_name}",
        )
        if prop_name in required:
            fields[prop_name] = (field_type, ...)
        else:
            fields[prop_name] = (field_type | None, None)

    model = create_model(name, __base__=BaseModel, **fields)  # type: ignore[call-overload]
    return cast(type[BaseModel], model)


def _provider_schema(validator: type[BaseModel]) -> dict[str, Any]:
    return validator.model_json_schema()


def _validate_output(value: Any, validator: type[BaseModel]) -> Any:
    try:
        validated = validator.model_validate(value)
    except ValidationError as exc:
        raise ValueError(f"LLM response did not match schema: {exc}") from exc
    return validated.model_dump()


def _parse_json_response(text: str) -> Any:
    cleaned = _JSON_FENCE_RE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM response was not valid JSON: {exc}") from exc


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    timeout: float,
    api_label: str,
) -> dict[str, Any]:
    if not url.startswith(("http://", "https://")):
        raise ValueError("Only http and https schemes are allowed.")

    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
            return cast(dict[str, Any], json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        err_msg = exc.read().decode("utf-8")
        raise RuntimeError(f"{api_label} API Error ({exc.code}): {err_msg}") from exc


def _extract_usage(data: dict[str, Any], provider_name: str) -> dict[str, int | None]:
    usage_raw = data.get("usage")
    if not isinstance(usage_raw, dict):
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}

    if provider_name == "anthropic":
        input_tokens = usage_raw.get("input_tokens")
        output_tokens = usage_raw.get("output_tokens")
        total_tokens: int | None = None
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            total_tokens = input_tokens + output_tokens
        return {
            "input_tokens": input_tokens if isinstance(input_tokens, int) else None,
            "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
            "total_tokens": total_tokens,
        }

    input_tokens = usage_raw.get("prompt_tokens")
    output_tokens = usage_raw.get("completion_tokens")
    total_tokens = usage_raw.get("total_tokens")
    if total_tokens is None and isinstance(input_tokens, int) and isinstance(output_tokens, int):
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens if isinstance(input_tokens, int) else None,
        "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
        "total_tokens": total_tokens if isinstance(total_tokens, int) else None,
    }


def _resolve_api_key(
    provider: OpenAICompatibleProvider | AnthropicProvider, api_key: str | None
) -> str:
    if api_key:
        return api_key
    for env_var in provider.api_key_env:
        value = os.environ.get(env_var)
        if value:
            return value
    if provider.name == "ollama":
        return "ollama"
    env_hint = ", ".join(provider.api_key_env) if provider.api_key_env else "none"
    raise ValueError(
        f"API key for provider '{provider.name}' is missing. "
        f"Provide it in node inputs or set one of: {env_hint}."
    )


def _resolve_base_url(
    provider: OpenAICompatibleProvider | AnthropicProvider, base_url: str | None
) -> str:
    if base_url:
        return base_url.rstrip("/")
    if provider.default_base_url:
        return provider.default_base_url.rstrip("/")
    raise ValueError(
        f"Provider '{provider.name}' requires 'base_url'. "
        "Set it in the node inputs, e.g. http://localhost:11434/v1."
    )


@dataclass(frozen=True)
class OpenAICompatibleProvider:
    name: str
    api_key_env: tuple[str, ...]
    default_base_url: str
    api_label: str

    def build_request(self, req: LLMRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = f"{req.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {req.api_key}",
        }

        messages: list[dict[str, str]] = []
        if req.system_prompt:
            messages.append({"role": "system", "content": req.system_prompt})
        messages.append({"role": "user", "content": req.prompt})

        payload: dict[str, Any] = {
            "model": req.model,
            "messages": messages,
            "max_tokens": req.max_tokens,
        }
        if req.temperature is not None:
            payload["temperature"] = req.temperature

        if req.output_schema and req.output_validator is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": req.schema_name,
                    "schema": _provider_schema(req.output_validator),
                    "strict": True,
                },
            }

        return url, headers, payload

    def parse_response(self, data: dict[str, Any], req: LLMRequest) -> Any:
        content = data["choices"][0]["message"]["content"]
        if req.output_schema:
            return _parse_json_response(content)
        return content


@dataclass(frozen=True)
class AnthropicProvider:
    name: str = "anthropic"
    api_key_env: tuple[str, ...] = ("ANTHROPIC_API_KEY",)
    default_base_url: str = "https://api.anthropic.com/v1"
    api_label: str = "Anthropic"

    def build_request(self, req: LLMRequest) -> tuple[str, dict[str, str], dict[str, Any]]:
        url = f"{req.base_url}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": req.api_key,
            "anthropic-version": "2023-06-01",
        }

        payload: dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        if req.system_prompt:
            payload["system"] = req.system_prompt
        if req.temperature is not None:
            payload["temperature"] = req.temperature

        if req.output_schema and req.output_validator is not None:
            payload["tools"] = [
                {
                    "name": req.schema_name,
                    "description": "Return structured output matching the requested schema.",
                    "input_schema": _provider_schema(req.output_validator),
                }
            ]
            payload["tool_choice"] = {"type": "tool", "name": req.schema_name}

        return url, headers, payload

    def parse_response(self, data: dict[str, Any], req: LLMRequest) -> Any:
        if req.output_schema:
            for block in data.get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == req.schema_name:
                    return block.get("input")
            stop_reason = data.get("stop_reason", "unknown")
            raise ValueError(
                f"Anthropic response did not include structured tool output (stop_reason={stop_reason})."
            )

        for block in data.get("content", []):
            if block.get("type") == "text":
                return block.get("text", "")
        raise ValueError("Anthropic response did not include text content.")


PROVIDERS: dict[str, OpenAICompatibleProvider | AnthropicProvider] = {
    "openai": OpenAICompatibleProvider(
        name="openai",
        api_key_env=("OPENAI_API_KEY",),
        default_base_url="https://api.openai.com/v1",
        api_label="OpenAI",
    ),
    "ollama": OpenAICompatibleProvider(
        name="ollama",
        api_key_env=(),
        default_base_url="http://localhost:11434/v1",
        api_label="Ollama",
    ),
    "openai-compatible": OpenAICompatibleProvider(
        name="openai-compatible",
        api_key_env=("OPENAI_API_KEY",),
        default_base_url="",
        api_label="OpenAI-compatible",
    ),
    "anthropic": AnthropicProvider(),
}


def _get_provider(provider_name: str) -> OpenAICompatibleProvider | AnthropicProvider:
    provider = PROVIDERS.get(provider_name)
    if provider is None:
        available = ", ".join(sorted(PROVIDERS))
        raise ValueError(f"Unsupported LLM provider '{provider_name}'. Available: {available}.")
    return provider


@node(name="llm.generate")  # type: ignore[untyped-decorator]
def llm_generate(
    prompt: str,
    model: str = "gpt-3.5-turbo",
    system_prompt: str | None = None,
    api_key: str | None = None,
    provider: str = "openai",
    base_url: str | None = None,
    max_tokens: int = 1024,
    temperature: float | None = None,
    timeout: float = 60.0,
    output_schema: Annotated[dict[str, Any] | None, Field(alias="schema")] = None,
    schema_name: str = "structured_output",
    ctx: NodeContext | None = None,
) -> dict[str, Any]:
    """Generate text or structured output from an LLM provider.

    Args:
        prompt: The user prompt.
        model: The model ID (default: gpt-3.5-turbo).
        system_prompt: Optional system instruction.
        api_key: API key (falls back to provider-specific environment variables).
        provider: One of openai, anthropic, ollama, openai-compatible.
        base_url: Optional custom API endpoint base URL.
        max_tokens: Maximum tokens to generate.
        temperature: Optional sampling temperature.
        timeout: HTTP request timeout in seconds.
        schema: Optional JSON Schema subset for structured output (YAML key: ``schema``).
        schema_name: Name used by providers when requesting structured output.
        ctx: Execution context (injected by the engine).

    Outputs:
        output: Generated text or validated structured object when schema is set.
        usage: Token counts (input_tokens, output_tokens, total_tokens).
        model: Model ID used for the request.
        provider: Provider name used for the request.
    """
    llm_provider = _get_provider(provider)

    output_validator: type[BaseModel] | None = None
    if output_schema is not None:
        output_validator = _build_output_validator(output_schema, name=schema_name)

    resolved_api_key = _resolve_api_key(llm_provider, api_key)
    resolved_base_url = _resolve_base_url(llm_provider, base_url)

    request = LLMRequest(
        prompt=prompt,
        model=model,
        system_prompt=system_prompt,
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        output_schema=output_schema,
        schema_name=schema_name,
        output_validator=output_validator,
    )

    url, headers, payload = llm_provider.build_request(request)
    response_data = _post_json(
        url,
        headers,
        payload,
        timeout=timeout,
        api_label=llm_provider.api_label,
    )
    usage = _extract_usage(response_data, llm_provider.name)
    if ctx is not None:
        ctx.log.info(
            "llm.generate usage: input=%s output=%s total=%s (model=%s provider=%s)",
            usage["input_tokens"],
            usage["output_tokens"],
            usage["total_tokens"],
            model,
            provider,
        )

    raw_output = llm_provider.parse_response(response_data, request)
    if output_validator is not None:
        output = cast(dict[str, Any] | list[Any], _validate_output(raw_output, output_validator))
    else:
        output = raw_output

    return {
        "output": output,
        "usage": usage,
        "model": model,
        "provider": provider,
    }


__all__ = [
    "AnthropicProvider",
    "LLMRequest",
    "OpenAICompatibleProvider",
    "PROVIDERS",
    "llm_generate",
]
