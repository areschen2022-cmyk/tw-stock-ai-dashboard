from __future__ import annotations

import os

import requests

MAX_TELEGRAM_LEN = 4096
SAFE_CHUNK_LEN = 3900


class TelegramNotifier:
    def __init__(self, bot_token: str | None, chat_id: str | None, dry_run: bool = True) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.dry_run = dry_run

    @classmethod
    def from_env(cls, dry_run: bool = True) -> "TelegramNotifier":
        return cls(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            chat_id=os.getenv("TELEGRAM_CHAT_ID"),
            dry_run=dry_run,
        )

    def send(self, message: str) -> None:
        if self.dry_run:
            try:
                print(message)
            except UnicodeEncodeError:
                # Windows console may not support all Unicode characters; encode safely
                print(message.encode("utf-8", errors="replace").decode("ascii", errors="replace"))
            return
        if not self.bot_token or not self.chat_id:
            raise RuntimeError("Telegram credentials missing: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        for chunk in self._chunks(message):
            self._send_single(chunk)

    def _send_single(self, message: str) -> None:
        response = requests.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"},
            timeout=20,
        )
        response.raise_for_status()

    def _chunks(self, message: str) -> list[str]:
        if len(message) <= MAX_TELEGRAM_LEN:
            return [message]
        chunks: list[str] = []
        remaining = message
        while remaining:
            if len(remaining) <= SAFE_CHUNK_LEN:
                chunks.append(remaining)
                break
            split_at = remaining.rfind("\n", 0, SAFE_CHUNK_LEN)
            if split_at < SAFE_CHUNK_LEN // 2:
                split_at = SAFE_CHUNK_LEN
            chunks.append(remaining[:split_at].strip())
            remaining = remaining[split_at:].strip()
        return chunks
