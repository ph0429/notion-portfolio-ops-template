from __future__ import annotations

from itertools import islice


def managed_section_markers(key: str) -> tuple[str, str]:
    return (
        f"portfolio_sync_managed_section:{key}:start",
        f"portfolio_sync_managed_section:{key}:end",
    )


def chunked(items: list[dict], size: int) -> list[list[dict]]:
    iterator = iter(items)
    batches: list[list[dict]] = []
    while True:
        batch = list(islice(iterator, size))
        if not batch:
            return batches
        batches.append(batch)


def _chunk_text(value: str, limit: int = 1800) -> list[str]:
    if not value:
        return []
    chunks: list[str] = []
    remaining = value
    while remaining:
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]
    return chunks


def _rich_text(value: str) -> list[dict]:
    return [
        {
            "type": "text",
            "text": {"content": chunk},
        }
        for chunk in _chunk_text(value)
    ]


def _block(block_type: str, text: str) -> dict:
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": _rich_text(text)},
    }


def markdown_to_blocks(content: str) -> list[dict]:
    blocks: list[dict] = []
    paragraph_buffer: list[str] = []

    def flush_paragraph() -> None:
        if not paragraph_buffer:
            return
        joined = " ".join(part.strip() for part in paragraph_buffer if part.strip())
        paragraph_buffer.clear()
        if joined:
            blocks.append(_block("paragraph", joined))

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            flush_paragraph()
            continue

        if line.startswith("### "):
            flush_paragraph()
            blocks.append(_block("heading_3", line[4:].strip()))
            continue
        if line.startswith("## "):
            flush_paragraph()
            blocks.append(_block("heading_2", line[3:].strip()))
            continue
        if line.startswith("# "):
            flush_paragraph()
            blocks.append(_block("heading_1", line[2:].strip()))
            continue
        if line.startswith(("- ", "* ")):
            flush_paragraph()
            blocks.append(_block("bulleted_list_item", line[2:].strip()))
            continue

        number_prefix, separator, rest = line.partition(". ")
        if separator and number_prefix.isdigit():
            flush_paragraph()
            blocks.append(_block("numbered_list_item", rest.strip()))
            continue

        paragraph_buffer.append(line)

    flush_paragraph()
    return blocks


def managed_section_content_blocks(key: str, suggested_content: str, source_url: str | None = None) -> list[dict]:
    start_marker, end_marker = managed_section_markers(key)
    blocks: list[dict] = []
    if source_url:
        blocks.append(_block("paragraph", f"Source: {source_url}"))
    blocks.append(_block("paragraph", start_marker))
    blocks.extend(markdown_to_blocks(suggested_content))
    blocks.append(_block("paragraph", end_marker))
    return blocks

