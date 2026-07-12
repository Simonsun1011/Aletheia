"""Feed language gate tests."""

from __future__ import annotations

from backend.app.feed.language import (
    is_translated_from_english,
    language_allowed,
)
from backend.app.feed.relevance import load_relevance
from backend.app.models import FeedCard
from backend.app.services.feed_filter import card_is_relevant


def test_english_allowed():
    ok, lang = language_allowed(
        "Micron expands HBM capacity for AI servers",
        "Micron Technology said it will expand HBM production.",
    )
    assert ok and lang == "en"


def test_french_rejected():
    ok, lang = language_allowed(
        "EXTRAIT DE LA CONFÉRENCE INTERNATIONALE DE L'ASSOCIATION ALZHEIMER 2026",
        "Une nouvelle étude présentée à la Conférence internationale.",
    )
    assert not ok and lang == "other"


def test_spanish_rejected():
    ok, lang = language_allowed(
        "DEL CONGRESO INTERNACIONAL DE LA ALZHEIMER'S ASSOCIATION 2026",
        "En el Congreso Internacional se presentó una nueva investigación.",
    )
    assert not ok


def test_japanese_native_allowed():
    ok, lang = language_allowed(
        "東芝が半導体装置の受注を拡大、AI向け需要が追い風",
        "東京の発表によると、同社は先端パッケージ向け装置の出荷を増やした。",
    )
    assert ok and lang == "ja"


def test_chinese_native_allowed():
    ok, lang = language_allowed(
        "中芯国际发布一季报，先进制程产能持续爬坡",
        "公司称晶圆代工订单回暖，资本开支按计划推进。",
    )
    assert ok and lang == "zh"


def test_en_title_zh_summary_is_translation():
    assert is_translated_from_english(
        "Where Heritage Takes Form: The British Craftsmanship Behind FREELANDER",
        "GlobeNewswire 于 2026 年 7 月 12 日发布文章，题为上述英文标题。",
    )


def test_en_title_ja_summary_is_translation():
    assert is_translated_from_english(
        "TSMC expands CoWoS capacity for AI chips",
        "台湾積体回路はＡＩ向け先端包装の生産能力を拡大すると発表した。",
    )


def test_native_zh_summary_not_flagged_as_translation():
    assert not is_translated_from_english(
        "中芯国际发布一季报",
        "公司称晶圆代工订单回暖。",
    )


def test_read_path_purges_french_and_translated():
    lex = load_relevance(watchlist_tickers=["NVDA"])
    fr = FeedCard(
        id="fr1",
        fetched_at="2026-07-12T00:00:00Z",
        published_at="2026-07-12T00:00:00Z",
        source="PR Newswire Tech",
        title="PrimeBOT présente la robotique personnelle lors du Sommet",
        url="https://example.com/fr",
        summary="PrimeBOT a participé au Sommet mondial.",
        objects="[]",
        batch_date="2026-07-12",
    )
    assert card_is_relevant(fr, lex) is False

    translated = FeedCard(
        id="tr1",
        fetched_at="2026-07-12T00:00:00Z",
        published_at="2026-07-12T00:00:00Z",
        source="GlobeNewswire",
        title="Corgi Insurance Welcomes Robert E. Barlow Jr. as EVP",
        url="https://example.com/en",
        summary="Corgi Insurance 于 2026 年 7 月 11 日宣布任命 Barlow 为 EVP。",
        objects='["NVDA"]',
        batch_date="2026-07-12",
    )
    assert card_is_relevant(translated, lex) is False

    en = FeedCard(
        id="en1",
        fetched_at="2026-07-12T00:00:00Z",
        published_at="2026-07-12T00:00:00Z",
        source="Yahoo Finance",
        title="NVIDIA announces new GPU shipment update",
        url="https://example.com/nvda",
        summary="NVIDIA said it shipped additional AI GPUs this quarter.",
        objects='["NVDA"]',
        batch_date="2026-07-12",
    )
    assert card_is_relevant(en, lex) is True
