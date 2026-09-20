"""Structure-aware Markdown chunking for document indexing."""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.services.document_parser import ParsedDocument


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    content: str
    header_path: str | None = None
    page_number: int | None = None


class DocumentChunker:
    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = max(1, int(chunk_size))
        self.chunk_overlap = max(0, min(int(chunk_overlap), self.chunk_size - 1))

    def chunk(self, document: ParsedDocument) -> list[DocumentChunk]:
        markdown = document.markdown.strip()
        if not markdown:
            return []

        sections = self._sections(markdown)
        chunks: list[DocumentChunk] = []
        for header_path, section in sections:
            chunks.extend(self._chunk_section(section, header_path))
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

    @staticmethod
    def _is_atomic(block: str) -> bool:
        stripped = block.lstrip()
        return stripped.startswith("```") or (
            stripped.startswith("|") and "\n|" in stripped
        )
