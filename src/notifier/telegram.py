from __future__ import annotations

import os

import requests


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
            print(message)
            return
        if not self.bot_token or not self.chat_id:
            raise RuntimeError("Telegram credentials missing: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
        response = requests.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={"chat_id": self.chat_id, "text": message},
            timeout=20,
        )
        response.raise_for_status()
