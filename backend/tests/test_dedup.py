"""Feed dedup tests."""

from __future__ import annotations

from backend.app.feed.dedup import RawItem, merge_items


def test_merge_three_similar_titles_to_one_card_three_links():
    items = [
        RawItem(
            source="PR Newswire",
            title="Micron announces early HBM4 production",
            url="https://a.example/1",
            fetched_at="2026-07-11T12:00:00Z",
        ),
        RawItem(
            source="GlobeNewswire",
            title="Micron announces early production of HBM4",
            url="https://b.example/2",
            fetched_at="2026-07-11T12:01:00Z",
        ),
        RawItem(
            source="Yahoo",
            title="Micron: early HBM4 production announced",
            url="https://c.example/3",
            fetched_at="2026-07-11T12:02:00Z",
        ),
    ]
    groups = merge_items(items, threshold=0.55)
    assert len(groups) == 1
    assert len(groups[0].urls) == 3
