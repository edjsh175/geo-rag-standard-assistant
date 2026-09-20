from __future__ import annotations

from app.services.document_chunker import DocumentChunker
from app.services.document_parser import ParsedDocument


def test_chunker_respects_heading_boundaries_and_sets_header_path() -> None:
    document = ParsedDocument(
        markdown=(
            "# 第一章\n\n第一章内容。\n\n"
            "## 第一节\n\n第一节内容。\n\n"
            "# 第二章\n\n第二章内容。"
        )
    )

    chunks = DocumentChunker(chunk_size=80, chunk_overlap=10).chunk(document)

    assert [chunk.header_path for chunk in chunks] == [
        "第一章",
        "第一章 > 第一节",
        "第二章",
    ]
    assert "第二章内容" not in chunks[0].content
    assert chunks[1].content.startswith("## 第一节")


def test_chunker_keeps_markdown_table_and_fenced_code_atomic() -> None:
    document = ParsedDocument(
        markdown="""# 示例

前置说明。

| 字段 | 值 |
| --- | --- |
| A | 1 |
| B | 2 |

```python
def area():
    return 42
```
"""
    )

    chunks = DocumentChunker(chunk_size=45, chunk_overlap=5).chunk(document)

    table_chunks = [chunk for chunk in chunks if "| 字段 | 值 |" in chunk.content]
    code_chunks = [chunk for chunk in chunks if "```python" in chunk.content]
    assert len(table_chunks) == 1
    assert "| B | 2 |" in table_chunks[0].content
    assert len(code_chunks) == 1
    assert "return 42\n```" in code_chunks[0].content


def test_chunker_splits_long_plain_text_without_losing_content_order() -> None:
    body = "甲乙丙丁戊己庚辛壬癸" * 12
    document = ParsedDocument(markdown=f"# 长文本\n\n{body}")

    chunks = DocumentChunker(chunk_size=50, chunk_overlap=10).chunk(document)

    assert len(chunks) > 1
    assert all(chunk.header_path == "长文本" for chunk in chunks)
    assert chunks[0].content.startswith("# 长文本")
    assert body[:20] in chunks[0].content
