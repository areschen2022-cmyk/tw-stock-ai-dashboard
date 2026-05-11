from __future__ import annotations

from src.notifier.telegram import TelegramNotifier


def test_telegram_chunks_long_messages() -> None:
    notifier = TelegramNotifier("token", "chat", dry_run=False)
    message = "\n".join(f"line {i} " + ("x" * 120) for i in range(120))

    chunks = notifier._chunks(message)

    assert len(chunks) > 1
    assert all(len(chunk) <= 4096 for chunk in chunks)
    assert "line 0" in chunks[0]
