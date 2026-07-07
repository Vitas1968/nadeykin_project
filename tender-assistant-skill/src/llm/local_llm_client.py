from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .schema import DEFAULT_MODEL, DEFAULT_PROVIDER

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_API_KEY = "ollama"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_TOKENS = 512


@dataclass(frozen=True)
class LLMClientConfig:
    enabled: bool
    provider: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_tokens: int = DEFAULT_MAX_TOKENS


@dataclass(frozen=True)
class LLMClientResponse:
    ok: bool
    text: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL


def _env_bool(value: str | None) -> bool:
    return str(value).strip().lower() == "true"


def _env_timeout_seconds(value: str | None) -> int:
    return _env_positive_int(value, DEFAULT_TIMEOUT_SECONDS)


def _env_positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default

    stripped = value.strip()
    if not stripped:
        return default

    try:
        # int() intentionally accepts values like "+30" and "030" as 30.
        parsed_value = int(stripped)
    except ValueError:
        return default

    if parsed_value <= 0:
        return default
    return parsed_value


def load_config_from_env() -> LLMClientConfig:
    return LLMClientConfig(
        enabled=_env_bool(os.environ.get("TENDER_LLM_ENABLED")),
        provider=os.environ.get("TENDER_LLM_PROVIDER", DEFAULT_PROVIDER).strip() or DEFAULT_PROVIDER,
        base_url=os.environ.get("TENDER_LLM_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        model=os.environ.get("TENDER_LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        api_key=os.environ.get("TENDER_LLM_API_KEY", DEFAULT_API_KEY).strip() or DEFAULT_API_KEY,
        timeout_seconds=_env_timeout_seconds(os.environ.get("TENDER_LLM_TIMEOUT_SECONDS")),
        max_tokens=_env_positive_int(os.environ.get("TENDER_LLM_MAX_TOKENS"), DEFAULT_MAX_TOKENS),
    )


class LocalLLMClient:
    def __init__(self, config: LLMClientConfig | None = None) -> None:
        self.config = config if config is not None else load_config_from_env()

    def chat(self, prompt: str) -> LLMClientResponse:
        """Return parsed LLM responses; transport errors become ok=False responses."""
        if not self.config.enabled:
            return LLMClientResponse(
                ok=False,
                error_type="disabled",
                error_message="TENDER_LLM_ENABLED is not true.",
                provider=self.config.provider,
                model=self.config.model,
            )

        request = self._build_request(prompt)
        provider = self.config.provider
        start_time = time.monotonic()
        print(
            "LLM request start: "
            f"provider={provider}, model={self.config.model}, timeout={self.config.timeout_seconds}, "
            f"max_tokens={self.config.max_tokens}, prompt_chars={len(prompt)}",
            file=sys.stderr,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                response_text = response.read().decode("utf-8")

        except urllib.error.HTTPError as exc:
            error_type = "http_error"
            error_message = f"HTTP {exc.code}: {exc.reason}"
            elapsed = time.monotonic() - start_time
            print(
                "LLM request failed: "
                f"provider={provider}, model={self.config.model}, elapsed_sec={round(elapsed, 3)}, "
                f"error_type={type(exc).__name__}, error_message={str(exc)}",
                file=sys.stderr,
            )
            return self._error_response(error_type, error_message)
        except urllib.error.URLError as exc:
            error_type = "url_error"
            error_message = str(exc.reason)
            elapsed = time.monotonic() - start_time
            print(
                "LLM request failed: "
                f"provider={provider}, model={self.config.model}, elapsed_sec={round(elapsed, 3)}, "
                f"error_type={type(exc).__name__}, error_message={str(exc)}",
                file=sys.stderr,
            )
            return self._error_response(error_type, error_message)
        except TimeoutError as exc:
            error_type = "timeout"
            error_message = str(exc)
            elapsed = time.monotonic() - start_time
            print(
                "LLM request failed: "
                f"provider={provider}, model={self.config.model}, elapsed_sec={round(elapsed, 3)}, "
                f"error_type={type(exc).__name__}, error_message={str(exc)}",
                file=sys.stderr,
            )
            return self._error_response(error_type, error_message)
        except OSError as exc:
            error_type = type(exc).__name__
            error_message = str(exc)
            elapsed = time.monotonic() - start_time
            print(
                "LLM request failed: "
                f"provider={provider}, model={self.config.model}, elapsed_sec={round(elapsed, 3)}, "
                f"error_type={type(exc).__name__}, error_message={str(exc)}",
                file=sys.stderr,
            )
            return self._error_response(error_type, error_message)

        elapsed = time.monotonic() - start_time
        print(
            "LLM request done: "
            f"provider={provider}, model={self.config.model}, elapsed_sec={round(elapsed, 3)}, "
            f"response_chars={len(response_text)}",
            file=sys.stderr,
        )

        try:
            payload = json.loads(response_text)
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            return self._error_response("invalid_response", str(exc))

        if not isinstance(content, str):
            return self._error_response("invalid_response", "Response content must be a string.")

        return LLMClientResponse(
            ok=True,
            text=content,
            provider=self.config.provider,
            model=self.config.model,
        )

    def _build_request(self, prompt: str) -> urllib.request.Request:
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": self.config.max_tokens,
            "stream": False,
        }
        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        return urllib.request.Request(endpoint, data=data, headers=headers, method="POST")

    def _error_response(self, error_type: str, error_message: str) -> LLMClientResponse:
        return LLMClientResponse(
            ok=False,
            error_type=error_type,
            error_message=error_message,
            provider=self.config.provider,
            model=self.config.model,
        )
