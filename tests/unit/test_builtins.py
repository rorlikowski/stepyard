import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stepyard.cli.run.inputs import prompt_label as _prompt_label
from stepyard.plugin import discover_capabilities
from stepyard.sdk.inputs import InputRequest
from stepyard.sdk.testing import fake_context
from stepyard_builtin.file import file_list, file_read, file_write
from stepyard_builtin.http import http_request
from stepyard_builtin.llm import llm_generate
from stepyard_builtin.shell import shell_run
from stepyard_builtin.system import flow_route, human_input, human_input_env_key
from stepyard_builtin.text import text_replace, text_template
from stepyard_builtin.triggers import cron_trigger

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": ["bug", "feature", "question"]},
        "priority": {"type": "string", "enum": ["low", "medium", "high"]},
        "summary": {"type": "string"},
    },
    "required": ["category", "priority", "summary"],
}


def _mock_urlopen_response(payload: dict) -> MagicMock:
    mock_res = MagicMock()
    mock_res.read.return_value = json.dumps(payload).encode("utf-8")
    mock_res.__enter__.return_value = mock_res
    return mock_res


def test_filesystem_nodes(tmp_path):
    file_path = tmp_path / "test.txt"
    # Write
    written_path = file_write(str(file_path), "Hello Stepyard")
    assert os.path.exists(written_path)

    # Read
    content = file_read(str(file_path))
    assert content == "Hello Stepyard"

    # List
    files = file_list(str(tmp_path))
    assert "test.txt" in files


def test_text_nodes():
    res = text_template("Hello ${name} from ${city}!", {"name": "Alice", "city": "Warsaw"})
    assert res == "Hello Alice from Warsaw!"

    res = text_replace("Stepyard Core", "Core", "MVP")
    assert res == "Stepyard MVP"


def test_human_input_uses_default_when_noninteractive(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert human_input("Choose a team", default="support") == "support"


def test_human_input_validates_choices_when_noninteractive(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert (
        human_input("Choose a team", default="billing", choices=["billing", "support"]) == "billing"
    )


def test_human_input_reads_precollected_env(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setenv(human_input_env_key("ask_message"), "hello from cli")

    value = human_input("Message", ctx=SimpleNamespace(step_id="ask_message"))

    assert value == "hello from cli"


def test_human_input_reuses_logical_step_env_for_repeated_visits(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setenv(human_input_env_key("ask_message"), "hello again")

    value = human_input("Message", ctx=SimpleNamespace(step_id="ask_message#2"))

    assert value == "hello again"


def test_human_input_registers_pre_run_collector():
    registry = discover_capabilities(os.getcwd())
    collector = registry.get_input_collector("human.input")
    assert collector is not None

    request = collector("ask_message", SimpleNamespace(), {"prompt": "Message"}, {})

    assert isinstance(request, InputRequest)
    assert request.env_key == human_input_env_key("ask_message")
    assert request.prompt == "Message"


def test_pre_run_prompt_label_is_plain_when_needed():
    assert _prompt_label("Message", "default") == "Message [default]: "


def test_flow_route_returns_handoff_object():
    res = flow_route("support.escalate", payload={"ticket": "T-1"}, reason="user asked")
    assert res == {
        "routed": True,
        "target": "support.escalate",
        "payload": {"ticket": "T-1"},
        "reason": "user asked",
    }


def test_cron_trigger_accepts_expression_alias():
    trigger = cron_trigger(expression="0 2 * * *")

    assert trigger is not None


def test_shell_node():
    res = shell_run("echo 'Hello shell'")
    assert res["code"] == 0
    assert "Hello shell" in res["stdout"]


@patch("urllib.request.urlopen")
def test_http_request_node(mock_urlopen):
    # Mock response
    mock_res = MagicMock()
    mock_res.read.return_value = b'{"success": true}'
    mock_res.status = 200
    mock_res.headers = {"Content-Type": "application/json"}
    mock_urlopen.return_value.__enter__.return_value = mock_res

    res = http_request("https://api.example.com", method="GET")
    assert res["status"] == 200
    assert res["body"] == {"success": True}


@patch("urllib.request.urlopen")
def test_llm_generate_openai_returns_string(mock_urlopen, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    mock_urlopen.return_value = _mock_urlopen_response(
        {
            "choices": [{"message": {"content": "Hello from OpenAI"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    )

    result = llm_generate(prompt="Say hello", model="gpt-4o-mini", ctx=fake_context())

    assert result["output"] == "Hello from OpenAI"
    assert result["usage"] == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }
    assert result["model"] == "gpt-4o-mini"
    assert result["provider"] == "openai"
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == "https://api.openai.com/v1/chat/completions"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["max_tokens"] == 1024
    assert "response_format" not in payload


@patch("urllib.request.urlopen")
def test_llm_generate_openai_structured_output(mock_urlopen, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    structured = {
        "category": "bug",
        "priority": "high",
        "summary": "Login fails",
    }
    mock_urlopen.return_value = _mock_urlopen_response(
        {
            "choices": [{"message": {"content": json.dumps(structured)}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 12, "total_tokens": 32},
        }
    )

    result = llm_generate(
        prompt="Classify ticket",
        model="gpt-4o-mini",
        output_schema=CLASSIFY_SCHEMA,
        ctx=fake_context(),
    )

    assert result["output"] == structured
    assert result["usage"]["total_tokens"] == 32
    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["name"] == "structured_output"
    assert payload["response_format"]["json_schema"]["strict"] is True


@patch("urllib.request.urlopen")
def test_llm_generate_ollama_uses_local_base_url(mock_urlopen):
    structured = {"category": "feature", "priority": "low", "summary": "Add export"}
    mock_urlopen.return_value = _mock_urlopen_response(
        {
            "choices": [{"message": {"content": json.dumps(structured)}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 6, "total_tokens": 14},
        }
    )

    result = llm_generate(
        prompt="Classify",
        provider="ollama",
        model="llama3.2",
        output_schema=CLASSIFY_SCHEMA,
        ctx=fake_context(),
    )

    assert result["output"] == structured
    assert result["provider"] == "ollama"
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == "http://localhost:11434/v1/chat/completions"
    headers = {k.lower(): v for k, v in request.header_items()}
    assert headers["authorization"] == "Bearer ollama"


@patch("urllib.request.urlopen")
def test_llm_generate_openai_compatible_with_base_url(mock_urlopen):
    mock_urlopen.return_value = _mock_urlopen_response(
        {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }
    )
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
        result = llm_generate(
            prompt="Hello",
            provider="openai-compatible",
            base_url="http://localhost:8080/v1",
            ctx=fake_context(),
        )
    assert result["output"] == "ok"
    assert mock_urlopen.call_args[0][0].full_url == "http://localhost:8080/v1/chat/completions"


def test_llm_generate_openai_compatible_missing_base_url():
    with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
        with pytest.raises(ValueError, match="requires 'base_url'"):
            llm_generate(prompt="Hello", provider="openai-compatible")


@patch("urllib.request.urlopen")
def test_llm_generate_anthropic_structured_output(mock_urlopen, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    structured = {"category": "question", "priority": "medium", "summary": "How to reset?"}
    mock_urlopen.return_value = _mock_urlopen_response(
        {
            "content": [
                {
                    "type": "tool_use",
                    "name": "structured_output",
                    "input": structured,
                }
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 30, "output_tokens": 15},
        }
    )

    result = llm_generate(
        prompt="Classify ticket",
        provider="anthropic",
        model="claude-3-5-sonnet-20241022",
        max_tokens=256,
        output_schema=CLASSIFY_SCHEMA,
        ctx=fake_context(),
    )

    assert result["output"] == structured
    assert result["usage"] == {
        "input_tokens": 30,
        "output_tokens": 15,
        "total_tokens": 45,
    }
    payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    assert payload["max_tokens"] == 256
    assert payload["tools"][0]["name"] == "structured_output"
    assert payload["tool_choice"] == {"type": "tool", "name": "structured_output"}


@patch("urllib.request.urlopen")
def test_llm_generate_logs_usage(mock_urlopen, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    mock_urlopen.return_value = _mock_urlopen_response(
        {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
    )
    ctx = fake_context()
    ctx.log = MagicMock()

    llm_generate(prompt="Hello", ctx=ctx)

    ctx.log.info.assert_called_once()
    assert "usage" in ctx.log.info.call_args[0][0]


@patch("urllib.request.urlopen")
def test_llm_generate_missing_usage_returns_none(mock_urlopen, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    mock_urlopen.return_value = _mock_urlopen_response(
        {"choices": [{"message": {"content": "ok"}}]}
    )

    result = llm_generate(prompt="Hello", ctx=fake_context())

    assert result["usage"] == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_llm_generate_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported LLM provider 'unknown'"):
        llm_generate(prompt="Hello", provider="unknown")


@patch("urllib.request.urlopen")
def test_llm_generate_schema_validation_failure(mock_urlopen, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    mock_urlopen.return_value = _mock_urlopen_response(
        {"choices": [{"message": {"content": json.dumps({"category": "bug"})}}]}
    )

    with pytest.raises(ValueError, match="LLM response did not match schema"):
        llm_generate(prompt="Classify", output_schema=CLASSIFY_SCHEMA, ctx=fake_context())


def test_llm_generate_invalid_schema_keyword():
    with pytest.raises(ValueError, match="Unsupported JSON Schema keyword"):
        llm_generate(
            prompt="Classify",
            output_schema={
                "type": "object",
                "properties": {"name": {"type": "string", "minLength": 1}},
                "required": ["name"],
            },
        )


def test_llm_generate_input_model_accepts_schema_yaml_key():
    input_model = llm_generate.__stepyard_input_model__
    validated = input_model.model_validate(
        {
            "prompt": "Classify",
            "schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        }
    )
    assert validated.output_schema is not None
    assert validated.output_schema["type"] == "object"
