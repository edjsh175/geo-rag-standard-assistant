"""Structure-aware Markdown chunking for document indexing."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Sequence
import uuid

from app.services.document_parser import ParsedBlock, ParsedDocument


GEOAI_CHUNK_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "chunk.geoai.local")


def compute_content_hash(content: str) -> str:
    """Compute deterministic SHA-256 fingerprint for chunk content."""
    return hashlib.sha256((content or "").strip().encode("utf-8")).hexdigest()


def compute_chunk_uid(
    document_id: str,
    section_path: str | None,
    chunk_index: int,
    content_hash: str,
) -> str:
    """Deterministically derive stable logical chunk_uid (RFC 4122 UUIDv5).

    Reindexing logically unchanged chunks retains their citation / Evidence identity.
    """
    norm_doc = str(document_id or "").strip()
    norm_section = str(section_path or "").strip()
    norm_index = int(chunk_index)
    norm_hash = str(content_hash or "").strip()
    key = f"{norm_doc}:{norm_section}:{norm_index}:{norm_hash}"
    return str(uuid.uuid5(GEOAI_CHUNK_NAMESPACE, key))


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    content: str
    header_path: str | None = None
    page_number: int | None = None
    content_hash: str | None = None
    chunk_policy_id: str = "section_based_v1"
    content_role: str = "prose"
    source_element_orders: list[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.content_hash:
            object.__setattr__(self, "content_hash", compute_content_hash(self.content))


class DocumentChunker:
    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = max(1, int(chunk_size))
        self.chunk_overlap = max(0, min(int(chunk_overlap), self.chunk_size - 1))

    def chunk(self, document: ParsedDocument) -> list[DocumentChunk]:
        markdown = document.markdown.strip()
        if not markdown:
            return []

        if getattr(document, "blocks", None):
            return self._chunk_blocks(document.blocks)

        sections = self._sections(markdown)
        chunks: list[DocumentChunk] = []
        for header_path, section in sections:
            chunks.extend(self._chunk_section(section, header_path))
        return chunks

    def _chunk_blocks(self, blocks: list[ParsedBlock]) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []
        buffer: list[ParsedBlock] = []
        buffer_len = 0
        current_header: str | None = None
        current_page: int | None = None

        def flush_buffer() -> None:
            nonlocal buffer, buffer_len
            if not buffer:
                return
            combined_text = "\n\n".join(b.content for b in buffer).strip()
            orders = [b.order for b in buffer]
            p_nums = [b.page_number for b in buffer if b.page_number is not None]
            page_num = p_nums[0] if p_nums else None
            chunks.append(
                DocumentChunk(
                    content=combined_text,
                    header_path=current_header,
                    page_number=page_num,
                    chunk_policy_id="section_based_v1",
                    content_role="prose",
                    source_element_orders=orders,
                )
            )
            buffer = []
            buffer_len = 0

        for block in blocks:
            # Page or section boundary flush
            page_changed = (
                block.page_number is not None
                and current_page is not None
                and block.page_number != current_page
            )
            if block.header_path != current_header or page_changed:
                flush_buffer()
                current_header = block.header_path
                current_page = block.page_number
            elif current_page is None and block.page_number is not None:
                current_page = block.page_number

            if block.kind == "heading":
                flush_buffer()
                buffer.append(block)
                buffer_len = len(block.content)
                continue

            if block.kind == "table":
                flush_buffer()
                if len(block.content) > self.chunk_size:
                    chunks.extend(
                        self._split_table_row_groups(
                            block.content,
                            header_path=current_header,
                            page_number=block.page_number,
                            source_order=block.order,
                        )
                    )
                else:
                    chunks.append(
                        DocumentChunk(
                            content=block.content.strip(),
                            header_path=current_header,
                            page_number=block.page_number,
                            chunk_policy_id="section_based_v1",
                            content_role="table",
                            source_element_orders=[block.order],
                        )
                    )
                continue

            if block.kind == "code":
                flush_buffer()
                chunks.append(
                    DocumentChunk(
                        content=block.content.strip(),
                        header_path=current_header,
                        page_number=block.page_number,
                        chunk_policy_id="section_based_v1",
                        content_role="code",
                        source_element_orders=[block.order],
                    )
                )
                continue

            # Paragraph
            if len(block.content) > self.chunk_size:
                heading_prefix = ""
                if buffer and all(b.kind == "heading" for b in buffer):
                    heading_prefix = "\n\n".join(b.content for b in buffer)
                    buffer = []
                    buffer_len = 0
                else:
                    flush_buffer()
                split_chunks = self._split_plain(
                    f"{heading_prefix}\n\n{block.content}" if heading_prefix else block.content,
                    current_header,
                )
                for sc in split_chunks:
                    chunks.append(
                        DocumentChunk(
                            content=sc.content,
                            header_path=current_header,
                            page_number=block.page_number,
                            chunk_policy_id="section_based_v1",
                            content_role="prose",
                            source_element_orders=[block.order],
                        )
                    )
                continue

            additional_len = len(block.content) + (2 if buffer else 0)
            if buffer and (buffer_len + additional_len > self.chunk_size):
                flush_buffer()
                buffer = [block]
                buffer_len = len(block.content)
            else:
                buffer.append(block)
                buffer_len += additional_len

        flush_buffer()
        return chunks

    def _split_table_row_groups(
        self,
        table_text: str,
        *,
        header_path: str | None = None,
        page_number: int | None = None,
        source_order: int | None = None,
    ) -> list[DocumentChunk]:
        lines = [line.strip() for line in table_text.strip().splitlines() if line.strip()]
        if len(lines) <= 2:
            return [
                DocumentChunk(
                    content=table_text.strip(),
                    header_path=header_path,
                    page_number=page_number,
                    chunk_policy_id="table_rowgroup_v1",
                    content_role="table",
                    source_element_orders=[source_order] if source_order is not None else [],
                )
            ]

        table_header = lines[0]
        separator = lines[1]
        header_prefix = f"{table_header}\n{separator}\n"
        data_rows = lines[2:]

        row_groups: list[list[str]] = []
        current_group: list[str] = []
        current_len = len(header_prefix)

        for row in data_rows:
            row_len = len(row) + 1
            if current_group and (current_len + row_len > self.chunk_size):
                row_groups.append(current_group)
                current_group = [row]
                current_len = len(header_prefix) + row_len
            else:
                current_group.append(row)
                current_len += row_len

        if current_group:
            row_groups.append(current_group)

        chunks: list[DocumentChunk] = []
        for group in row_groups:
            group_content = header_prefix + "\n".join(group)
            chunks.append(
                DocumentChunk(
                    content=group_content.strip(),
                    header_path=header_path,
                    page_number=page_number,
                    chunk_policy_id="table_rowgroup_v1",
                    content_role="table",
                    source_element_orders=[source_order] if source_order is not None else [],
                )
            )
        return chunks

    def _sections(self, markdown: str) -> list[tuple[str | None, str]]:
        header_stack: list[str] = []
        current_header: str | None = None
        current_lines: list[str] = []
        sections: list[tuple[str | None, str]] = []

        for line in markdown.splitlines():
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match:
                if current_lines:
                    sections.append((current_header, "\n".join(current_lines).strip()))
                level = len(match.group(1))
                title = match.group(2).strip()
                header_stack = header_stack[: level - 1]
                while len(header_stack) < level - 1:
                    header_stack.append("")
                if len(header_stack) == level - 1:
                    header_stack.append(title)
                else:
                    header_stack[level - 1] = title
                current_header = " > ".join(item for item in header_stack if item)
                current_lines = [line]
            else:
                current_lines.append(line)
        if current_lines:
            sections.append((current_header, "\n".join(current_lines).strip()))
        return [(header, body) for header, body in sections if body]

    def _chunk_section(self, section: str, header_path: str | None) -> list[DocumentChunk]:
        blocks = self._atomic_blocks(section)
        output: list[DocumentChunk] = []
        buffer = ""

        def flush() -> None:
            nonlocal buffer
            if buffer.strip():
                output.append(DocumentChunk(content=buffer.strip(), header_path=header_path))
                buffer = ""

        for block in blocks:
            if self._is_table(block) and len(block) > self.chunk_size:
                flush()
                output.extend(self._split_table_row_groups(block, header_path=header_path))
                continue
            if len(block) > self.chunk_size and not self._is_atomic(block):
                heading_prefix = ""
                if buffer and re.fullmatch(r"#{1,6}\s+.+", buffer.strip()):
                    heading_prefix = buffer.strip()
                    buffer = ""
                else:
                    flush()
                output.extend(
                    self._split_plain(
                        f"{heading_prefix}\n\n{block}" if heading_prefix else block,
                        header_path,
                    )
                )
                continue
            candidate = block if not buffer else f"{buffer}\n\n{block}"
            if buffer and len(candidate) > self.chunk_size:
                flush()
                buffer = block
            else:
                buffer = candidate
        flush()
        return output

    def _atomic_blocks(self, section: str) -> list[str]:
        lines = section.splitlines()
        blocks: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if line.lstrip().startswith("```"):
                fence = [line]
                index += 1
                while index < len(lines):
                    fence.append(lines[index])
                    if lines[index].lstrip().startswith("```"):
                        index += 1
                        break
                    index += 1
                blocks.append("\n".join(fence).strip())
                continue

            if self._is_table_line(line):
                table = [line]
                index += 1
                while index < len(lines) and self._is_table_line(lines[index]):
                    table.append(lines[index])
                    index += 1
                blocks.append("\n".join(table).strip())
                continue

            paragraph = [line]
            index += 1
            while index < len(lines):
                if not lines[index].strip():
                    index += 1
                    break
                if lines[index].lstrip().startswith("```") or self._is_table_line(lines[index]):
                    break
                paragraph.append(lines[index])
                index += 1
            text = "\n".join(paragraph).strip()
            if text:
                blocks.append(text)
        return blocks

    def _split_plain(self, text: str, header_path: str | None) -> list[DocumentChunk]:
        header_line = ""
        body = text
        lines = text.splitlines()
        if lines and re.match(r"^#{1,6}\s+", lines[0]):
            header_line = lines[0].strip()
            body = "\n".join(lines[1:]).strip()

        prefix = f"{header_line}\n\n" if header_line else ""
        available = max(1, self.chunk_size - len(prefix))
        overlap = min(self.chunk_overlap, max(0, available - 1))
        chunks: list[DocumentChunk] = []
        start = 0
        while start < len(body):
            end = min(len(body), start + available)
            content = f"{prefix}{body[start:end]}".strip()
            if content:
                chunks.append(DocumentChunk(content=content, header_path=header_path))
            if end >= len(body):
                break
            start = end - overlap
        return chunks

    @staticmethod
    def _is_table_line(line: str) -> bool:
        stripped = line.strip()
        return stripped.startswith("|") and stripped.endswith("|")

    @classmethod
    def _is_table(cls, block: str) -> bool:
        stripped = block.lstrip()
        return stripped.startswith("|") and "\n|" in stripped

    @classmethod
    def _is_atomic(cls, block: str) -> bool:
        stripped = block.lstrip()
        return stripped.startswith("```") or cls._is_table(block)
