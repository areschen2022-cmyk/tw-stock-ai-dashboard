from __future__ import annotations

import os
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
        response = requests.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://areschen2022-cmyk.github.io/tw-stock-ai-dashboard/",
                "X-Title": "tw-stock-ai",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("OpenRouter returned no choices")
        return str(choices[0].get("message", {}).get("content") or "")
