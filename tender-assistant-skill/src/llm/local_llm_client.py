from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .schema import DEFAULT_MODEL, DEFAULT_PROVIDER

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_API_KEY = "ollama"
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class LLMClientConfig:
    enabled: bool
    provider: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


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
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS

    stripped = value.strip()
    if not stripped:
        return DEFAULT_TIMEOUT_SECONDS

    try:
        # int() intentionally accepts values like "+30" and "030" as 30.
        timeout_seconds = int(stripped)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS

    if timeout_seconds <= 0:
        return DEFAULT_TIMEOUT_SECONDS
    return timeout_seconds


def load_config_from_env() -> LLMClientConfig:
    return LLMClientConfig(
        enabled=_env_bool(os.environ.get("TENDER_LLM_ENABLED")),
        provider=os.environ.get("TENDER_LLM_PROVIDER", DEFAULT_PROVIDER).strip() or DEFAULT_PROVIDER,
        base_url=os.environ.get("TENDER_LLM_BASE_URL", DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        model=os.environ.get("TENDER_LLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        api_key=os.environ.get("TENDER_LLM_API_KEY", DEFAULT_API_KEY).strip() or DEFAULT_API_KEY,
        timeout_seconds=_env_timeout_seconds(os.environ.get("TENDER_LLM_TIMEOUT_SECONDS")),
    )


class LocalLLMClient:
    def __init__(self, config: LLMClientConfig | None = None) -> None:
        self.config = config if config is not None else load_config_from_env()

    def chat(self, prompt: str) -> LLMClientResponse:
        if not self.config.enabled:
            return LLMClientResponse(
                ok=False,
                error_type="disabled",
                error_message="TENDER_LLM_ENABLED is not true.",
                provider=self.config.provider,
                model=self.config.model,
            )

        request = self._build_request(prompt)
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                response_text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return self._error_response("http_error", f"HTTP {exc.code}: {exc.reason}")
        except urllib.error.URLError as exc:
            return self._error_response("url_error", str(exc.reason))
        except TimeoutError as exc:
            return self._error_response("timeout", str(exc))
        except OSError as exc:
            return self._error_response(type(exc).__name__, str(exc))

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
