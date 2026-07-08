import json
import os
import unittest
import urllib.error
from unittest.mock import patch

import pytest

from llm.local_llm_client import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    LLMClientConfig,
    LocalLLMClient,
    load_config_from_env,
)


class _FakeResponse:
    def __init__(self, text):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self._text.encode("utf-8")


def _enabled_config(max_tokens=DEFAULT_MAX_TOKENS):
    return LLMClientConfig(
        enabled=True,
        provider="ollama",
        base_url="http://localhost:11434/v1",
        model="qwen2.5:14b",
        api_key="test-key",
        timeout_seconds=7,
        max_tokens=max_tokens,
    )


class LoadConfigFromEnvTimeoutTests(unittest.TestCase):
    def test_timeout_env_absent_uses_default(self):
        with patch.dict(os.environ, {}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, config.timeout_seconds)

    def test_timeout_env_valid_positive_int_uses_value(self):
        with patch.dict(os.environ, {"TENDER_LLM_TIMEOUT_SECONDS": "120"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(120, config.timeout_seconds)

    def test_timeout_env_empty_string_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_TIMEOUT_SECONDS": ""}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, config.timeout_seconds)

    def test_timeout_env_invalid_string_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_TIMEOUT_SECONDS": "abc"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, config.timeout_seconds)

    def test_timeout_env_zero_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_TIMEOUT_SECONDS": "0"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, config.timeout_seconds)

    def test_timeout_env_negative_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_TIMEOUT_SECONDS": "-5"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, config.timeout_seconds)

    def test_max_tokens_env_absent_uses_default(self):
        with patch.dict(os.environ, {}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_MAX_TOKENS, config.max_tokens)

    def test_max_tokens_env_valid_positive_int_uses_value(self):
        with patch.dict(os.environ, {"TENDER_LLM_MAX_TOKENS": "256"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(256, config.max_tokens)

    def test_max_tokens_env_empty_string_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_MAX_TOKENS": ""}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_MAX_TOKENS, config.max_tokens)

    def test_max_tokens_env_invalid_string_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_MAX_TOKENS": "abc"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_MAX_TOKENS, config.max_tokens)

    def test_max_tokens_env_zero_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_MAX_TOKENS": "0"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_MAX_TOKENS, config.max_tokens)

    def test_max_tokens_env_negative_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_MAX_TOKENS": "-1"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_MAX_TOKENS, config.max_tokens)

    def test_max_tokens_env_trimmed_positive_int_uses_value(self):
        with patch.dict(os.environ, {"TENDER_LLM_MAX_TOKENS": "  512  "}, clear=True):
            config = load_config_from_env()

        self.assertEqual(512, config.max_tokens)

    def test_max_tokens_env_float_like_uses_default(self):
        with patch.dict(os.environ, {"TENDER_LLM_MAX_TOKENS": "512.5"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(DEFAULT_MAX_TOKENS, config.max_tokens)

    def test_max_tokens_env_plus_prefixed_positive_int_uses_value(self):
        with patch.dict(os.environ, {"TENDER_LLM_MAX_TOKENS": "+512"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(512, config.max_tokens)

    def test_max_tokens_env_large_positive_int_has_no_upper_bound(self):
        with patch.dict(os.environ, {"TENDER_LLM_MAX_TOKENS": "99999999999"}, clear=True):
            config = load_config_from_env()

        self.assertEqual(99999999999, config.max_tokens)


class BuildRequestTests(unittest.TestCase):
    def test_build_request_body_matches_contract(self):
        client = LocalLLMClient(_enabled_config(max_tokens=256))

        request = client._build_request("Ответь одним словом: OK")

        self.assertEqual(
            {
                "model": "qwen2.5:14b",
                "messages": [{"role": "user", "content": "Ответь одним словом: OK"}],
                "temperature": 0,
                "max_tokens": 256,
                "stream": False,
            },
            json.loads(request.data.decode("utf-8")),
        )


def test_chat_logs_start_and_done_to_stderr_without_prompt_or_response(capsys):
    prompt = "FULL_PROMPT_SHOULD_NOT_APPEAR " * 20
    response_content = "FULL_RESPONSE_SHOULD_NOT_APPEAR"
    response_text = json.dumps({"choices": [{"message": {"content": response_content}}]})
    client = LocalLLMClient(_enabled_config(max_tokens=128))

    with patch("llm.local_llm_client.urllib.request.urlopen", return_value=_FakeResponse(response_text)):
        result = client.chat(prompt)

    captured = capsys.readouterr()
    assert result.ok
    assert result.text == response_content
    assert captured.out == ""
    assert "LLM request start: provider=ollama, model=qwen2.5:14b" in captured.err
    assert "timeout=7, max_tokens=128" in captured.err
    assert f"prompt_chars={len(prompt)}" in captured.err
    assert "LLM request done: provider=ollama, model=qwen2.5:14b" in captured.err
    assert f"response_chars={len(response_text)}" in captured.err
    assert prompt not in captured.err
    assert response_content not in captured.err


@pytest.mark.parametrize(
    ("exception", "expected_error_type", "expected_error_message"),
    [
        (TimeoutError("request timed out"), "timeout", "request timed out"),
        (
            urllib.error.HTTPError(
                url="http://localhost:11434/v1/chat/completions",
                code=500,
                msg="Internal Server Error",
                hdrs=None,
                fp=None,
            ),
            "http_error",
            "HTTP 500: Internal Server Error",
        ),
        (urllib.error.URLError("connection refused"), "url_error", "connection refused"),
        (ConnectionRefusedError("connection refused"), "ConnectionRefusedError", "connection refused"),
    ],
)
def test_chat_transport_errors_log_failed_and_return_error_response(
    capsys,
    exception,
    expected_error_type,
    expected_error_message,
):
    prompt = "FULL_FAILED_PROMPT_SHOULD_NOT_APPEAR " * 20
    client = LocalLLMClient(_enabled_config())

    with patch("llm.local_llm_client.urllib.request.urlopen", side_effect=exception):
        result = client.chat(prompt)

    captured = capsys.readouterr()
    assert not result.ok
    assert result.error_type == expected_error_type
    assert result.error_message == expected_error_message
    assert captured.out == ""
    assert "LLM request start: provider=ollama, model=qwen2.5:14b" in captured.err
    assert "LLM request failed: provider=ollama, model=qwen2.5:14b" in captured.err
    assert f"error_type={type(exception).__name__}" in captured.err
    assert f"error_message={str(exception)}" in captured.err
    assert prompt not in captured.err


if __name__ == "__main__":
    unittest.main()
