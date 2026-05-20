from __future__ import annotations

import os
import time
from typing import Any

import requests


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterClient:
    def __init__(self, api_key: str | None = None, timeout: int = 45) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def chat_json(self, model: str, messages: list[dict[str, str]], max_tokens: int = 900) -> str:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        response = self._post_with_retry(body)
        if response.status_code == 400 and "response_format" in response.text:
            body.pop("response_format", None)
            response = self._post_with_retry(body)
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no choices")
        return str(choices[0].get("message", {}).get("content") or "")

    def _post(self, body: dict[str, Any]) -> requests.Response:
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://areschen2022-cmyk.github.io/tw-stock-ai-dashboard/",
                "X-Title": "tw-stock-ai",
            },
            json=body,
            timeout=self.timeout,
        )
        return response

    def _post_with_retry(self, body: dict[str, Any]) -> requests.Response:
        last_response: requests.Response | None = None
        for attempt in range(3):
            response = self._post(body)
            if response.status_code != 429:
                return response
            last_response = response
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                wait_seconds = min(20, int(retry_after))
            else:
                wait_seconds = 4 * (attempt + 1)
            time.sleep(wait_seconds)
        if last_response is None:
            raise RuntimeError("OpenRouter retry failed before first response")
        return last_response
