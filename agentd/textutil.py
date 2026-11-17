"""文本切分：飞书单条文本消息有长度上限，长回复必须拆成多条。"""

from __future__ import annotations

DEFAULT_LIMIT = 1800


def split_text(text: str, limit: int = DEFAULT_LIMIT) -> list[str]:
    """按段落 → 行 → 硬切的顺序把文本拆成不超过 limit 的片段。

    优先在空行处断开，其次单行，最后才硬切，尽量不破坏 Markdown 结构。
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    for block in text.split("\n\n"):
        for piece in _fit(block, limit):
            candidate = f"{buf}\n\n{piece}" if buf else piece
            if len(candidate) <= limit:
                buf = candidate
            else:
                flush()
                buf = piece
    flush()
    return chunks


def _fit(block: str, limit: int) -> list[str]:
    """保证单个 block 也不超长：按行拼，超长行再硬切。"""
    if len(block) <= limit:
        return [block]

    pieces: list[str] = []
    buf = ""
    for line in block.split("\n"):
        while len(line) > limit:
            if buf:
                pieces.append(buf)
                buf = ""
            pieces.append(line[:limit])
            line = line[limit:]
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) <= limit:
            buf = candidate
        else:
            if buf:
                pieces.append(buf)
            buf = line
    if buf:
        pieces.append(buf)
    return pieces
