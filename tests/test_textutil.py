from __future__ import annotations

from agentd.textutil import split_text


def test_short_text_is_untouched() -> None:
    assert split_text("你好") == ["你好"]
    assert split_text("   ") == []


def test_long_text_is_split_under_limit() -> None:
    paragraphs = [f"第{i}段：" + "内容" * 100 for i in range(20)]
    text = "\n\n".join(paragraphs)
    chunks = split_text(text, limit=500)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    # 段落顺序不能乱，也不能丢
    joined = "\n\n".join(chunks)
    for paragraph in paragraphs:
        assert paragraph in joined


def test_single_huge_line_is_hard_split() -> None:
    text = "x" * 1234
    chunks = split_text(text, limit=400)

    assert all(len(chunk) <= 400 for chunk in chunks)
    assert "".join(chunks) == text
