from datetime import date

from src.news.web_theme import fetch_theme_signal
from src.news.theme_discovery import discover_emerging_themes
from src.storage.sqlite_store import SQLiteStore


def test_theme_discovery_finds_repeated_unmapped_terms() -> None:
    candidates = discover_emerging_themes(
        [
            "石英元件供應鏈升溫，台積電 2330 先進製程需求帶動",
            "法人點名石英元件與玻纖布需求延續",
            "石英元件廠受惠半導體設備拉貨",
            "被動元件強勢撐盤，國巨創高",
        ],
        {"passive_components": ["被動元件", "MLCC"]},
        stock_names={"2330": "台積電"},
        config={"enabled": True, "min_mentions": 2},
    )

    keywords = {item["keyword"] for item in candidates}
    assert "石英元件" in keywords
    assert "被動元件" not in keywords
    quartz = next(item for item in candidates if item["keyword"] == "石英元件")
    assert quartz["mentions"] >= 3
    assert "2330 台積電" in quartz["stock_hits"]


def test_theme_discovery_persists_recent_candidates(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "test.sqlite3")
    store.save_theme_discovery(
        [
            {
                "keyword": "石英元件",
                "score": 11,
                "mentions": 3,
                "stock_hits": ["2330 台積電"],
                "headlines": ["石英元件供應鏈升溫"],
            }
        ],
        date(2026, 6, 3),
    )

    summary = store.theme_discovery_summary(date(2026, 6, 3))

    assert summary["candidates"][0]["keyword"] == "石英元件"
    assert summary["candidates"][0]["total_mentions"] == 3
    assert summary["candidates"][0]["stock_hits"] == ["2330 台積電"]


def test_fetch_theme_signal_attaches_discovery_candidates(monkeypatch, tmp_path) -> None:
    class Response:
        text = """
        <rss><channel>
          <item><title>石英元件供應鏈升溫，台積電 2330 先進製程需求帶動</title></item>
          <item><title>法人點名石英元件與玻纖布需求延續</title></item>
          <item><title>石英元件廠受惠半導體設備拉貨</title></item>
        </channel></rss>
        """

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("src.news.web_theme.requests.get", lambda *args, **kwargs: Response())
    store = SQLiteStore(tmp_path / "test.sqlite3")

    signal = fetch_theme_signal(
        {
            "web_news": {
                "enabled": True,
                "urls": ["https://example.test/rss"],
                "theme_keywords": {"memory": ["記憶體"]},
                "theme_discovery": {"enabled": True, "min_mentions": 2},
            },
            "stock_names": {"2330": "台積電"},
            "opportunity": {"max_active_themes": 5},
            "theme_pools": {},
        },
        store=store,
        as_of=date(2026, 6, 3),
    )

    assert signal.discovered_themes[0]["keyword"] == "石英元件"
    assert store.theme_discovery_summary(date(2026, 6, 3))["candidates"][0]["keyword"] == "石英元件"
