"""Structure-preserving document parsing for uploaded-document indexing."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from app.services.document_text_extractor import DocumentTextExtractor


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    kind: str  # "heading" | "paragraph" | "table" | "code"
    content: str
    order: int
    header_path: str | None = None
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    markdown: str
    metadata: dict[str, Any] = field(default_factory=dict)
    blocks: list[ParsedBlock] = field(default_factory=list)


class DocumentParser:
    """Normalize supported documents into Markdown-like structured text."""

    def __init__(self, extractor: DocumentTextExtractor | Any | None = None) -> None:
        self.extractor = extractor or DocumentTextExtractor()

    def parse(self, path: Path, content_type: str | None = None) -> ParsedDocument:
        suffix = path.suffix.lower()
        normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()

        if suffix == ".md" or normalized_content_type == "text/markdown":
            raw_text = path.read_text(encoding="utf-8")
            blocks = self._parse_markdown_blocks(raw_text)
            return ParsedDocument(
                markdown=self._normalize_markdown(raw_text),
                blocks=blocks,
            )
        if suffix == ".docx" or normalized_content_type.endswith("wordprocessingml.document"):
            markdown, blocks = self._read_docx_ordered(path)
            return ParsedDocument(markdown=markdown, blocks=blocks)
        if suffix in {".xlsx", ".xlsm"} or normalized_content_type.endswith("spreadsheetml.sheet"):
            markdown, blocks = self._read_xlsx_blocks(path)
            return ParsedDocument(markdown=markdown, blocks=blocks)

        extracted = self.extractor.extract(path, content_type)
        blocks = []
        if getattr(extracted, "pages", None):
            for idx, page in enumerate(extracted.pages, start=1):
                page_text = str(page.get("text") or "").strip()
                page_num = page.get("page_number", idx)
                if page_text:
                    blocks.append(
                        ParsedBlock(
                            kind="paragraph",
                            content=page_text,
                            order=idx,
                            page_number=page_num,
                        )
                    )
        return ParsedDocument(
            markdown=self._normalize_markdown(extracted.text),
            metadata=dict(extracted.metadata or {}),
            blocks=blocks,
        )

    @classmethod
    def _read_docx_ordered(cls, path: Path) -> tuple[str, list[ParsedBlock]]:
        from docx import Document as DocxDocument
        from docx.oxml.table import CT_Tbl
        from docx.oxml.text.paragraph import CT_P
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        document = DocxDocument(str(path))
        blocks: list[ParsedBlock] = []
        markdown_parts: list[str] = []
        header_stack: list[str] = []
        current_header: str | None = None
        order = 1

        for child in document.element.body:
            if isinstance(child, CT_P):
                p = Paragraph(child, document)
                text = cls._normalize_inline(p.text)
                if not text:
                    continue
                style_name = (p.style.name or "").strip().lower() if p.style else ""
                heading_match = re.match(r"heading\s*(\d+)", style_name)
                if heading_match:
                    level = max(1, min(6, int(heading_match.group(1))))
                    header_stack = header_stack[: level - 1]
                    while len(header_stack) < level - 1:
                        header_stack.append("")
                    if len(header_stack) == level - 1:
                        header_stack.append(text)
                    else:
                        header_stack[level - 1] = text
                    current_header = " > ".join(item for item in header_stack if item)

                    formatted = f"{'#' * level} {text}"
                    markdown_parts.append(formatted)
                    blocks.append(
                        ParsedBlock(
                            kind="heading",
                            content=formatted,
                            order=order,
                            header_path=current_header,
                        )
                    )
                    order += 1
                else:
                    markdown_parts.append(text)
                    blocks.append(
                        ParsedBlock(
                            kind="paragraph",
                            content=text,
                            order=order,
                            header_path=current_header,
                        )
                    )
                    order += 1
            elif isinstance(child, CT_Tbl):
                table = Table(child, document)
                rows = [[cls._normalize_inline(cell.text) for cell in row.cells] for row in table.rows]
                table_text = cls._markdown_table(rows)
                if table_text:
                    markdown_parts.append(table_text)
                    blocks.append(
                        ParsedBlock(
                            kind="table",
                            content=table_text,
                            order=order,
                            header_path=current_header,
                        )
                    )
                    order += 1

        return cls._normalize_markdown("\n\n".join(markdown_parts)), blocks

    @classmethod
    def _read_docx(cls, path: Path) -> str:
        markdown, _ = cls._read_docx_ordered(path)
        return markdown

    @classmethod
    def _normalize_markdown(cls, text: str) -> str:
        normalized_lines: list[str] = []
        in_fence = False
        for raw_line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            if raw_line.lstrip().startswith("```"):
                in_fence = not in_fence
                normalized_lines.append(raw_line.rstrip())
                continue
            if in_fence:
                normalized_lines.append(raw_line.rstrip())
                continue

            line = raw_line.replace("\u00a0", " ").rstrip()
            line = re.sub(r"[ \t]+", " ", line).strip()
            normalized_lines.append(line)

        collapsed: list[str] = []
        previous_blank = False
        for line in normalized_lines:
            is_blank = not line
            if is_blank and previous_blank:
                continue
            collapsed.append(line)
            previous_blank = is_blank
        return "\n".join(collapsed).strip()

    @classmethod
    def _parse_markdown_blocks(cls, raw_text: str) -> list[ParsedBlock]:
        norm = cls._normalize_markdown(raw_text)
        if not norm:
            return []
        lines = norm.splitlines()
        blocks: list[ParsedBlock] = []
        order = 1
        header_stack: list[str] = []
        current_header: str | None = None
        idx = 0

        while idx < len(lines):
            line = lines[idx]
            if not line.strip():
                idx += 1
                continue

            # Heading
            h_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if h_match:
                level = len(h_match.group(1))
                title = h_match.group(2).strip()
                header_stack = header_stack[: level - 1]
                while len(header_stack) < level - 1:
                    header_stack.append("")
                if len(header_stack) == level - 1:
                    header_stack.append(title)
                else:
                    header_stack[level - 1] = title
                current_header = " > ".join(item for item in header_stack if item)
                blocks.append(
                    ParsedBlock(
                        kind="heading",
                        content=line,
                        order=order,
                        header_path=current_header,
                    )
                )
                order += 1
                idx += 1
                continue

            # Fenced code
            if line.lstrip().startswith("```"):
                code_lines = [line]
                idx += 1
                while idx < len(lines):
                    code_lines.append(lines[idx])
                    if lines[idx].lstrip().startswith("```"):
                        idx += 1
                        break
                    idx += 1
                blocks.append(
                    ParsedBlock(
                        kind="code",
                        content="\n".join(code_lines),
                        order=order,
                        header_path=current_header,
                    )
                )
                order += 1
                continue

            # Table
            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|"):
                table_lines = [line]
                idx += 1
                while idx < len(lines) and lines[idx].strip().startswith("|") and lines[idx].strip().endswith("|"):
                    table_lines.append(lines[idx])
                    idx += 1
                blocks.append(
                    ParsedBlock(
                        kind="table",
                        content="\n".join(table_lines),
                        order=order,
                        header_path=current_header,
                    )
                )
                order += 1
                continue

            # Paragraph
            para_lines = [line]
            idx += 1
            while idx < len(lines):
                next_line = lines[idx]
                if not next_line.strip() or next_line.lstrip().startswith("#") or next_line.lstrip().startswith("```"):
                    break
                next_stripped = next_line.strip()
                if next_stripped.startswith("|") and next_stripped.endswith("|"):
                    break
                para_lines.append(next_line)
                idx += 1
            blocks.append(
                ParsedBlock(
                    kind="paragraph",
                    content="\n".join(para_lines),
                    order=order,
                    header_path=current_header,
                )
            )
            order += 1

        return blocks

    @classmethod
    def _read_xlsx_blocks(cls, path: Path) -> tuple[str, list[ParsedBlock]]:
        from openpyxl import load_workbook

        workbook = load_workbook(path, data_only=True, read_only=True)
        blocks: list[ParsedBlock] = []
        markdown_parts: list[str] = []
        order = 1

        for sheet in workbook.worksheets:
            rows: list[list[str]] = []
            for row in sheet.iter_rows(values_only=True):
                values = [cls._cell_text(value) for value in row]
                while values and not values[-1]:
                    values.pop()
                if values:
                    rows.append(values)
            if not rows:
                continue
            sheet_heading = f"# {sheet.title}"
            markdown_parts.append(sheet_heading)
            blocks.append(
                ParsedBlock(
                    kind="heading",
                    content=sheet_heading,
                    order=order,
                    header_path=sheet.title,
                )
            )
            order += 1

            table_text = cls._markdown_table(rows)
            markdown_parts.append(table_text)
            blocks.append(
                ParsedBlock(
                    kind="table",
                    content=table_text,
                    order=order,
                    header_path=sheet.title,
                )
            )
            order += 1

        return cls._normalize_markdown("\n\n".join(markdown_parts)), blocks

    @classmethod
    def _read_xlsx(cls, path: Path) -> str:
        markdown, _ = cls._read_xlsx_blocks(path)
        return markdown

    @staticmethod
    def _normalize_inline(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").replace("\u00a0", " ")).strip()

    @classmethod
    def _markdown_table(cls, rows: list[list[str]]) -> str:
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        normalized = [row + [""] * (width - len(row)) for row in rows]
        header = normalized[0]
        lines = [
            "| " + " | ".join(cls._escape_table_cell(value) for value in header) + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
        ]
        lines.extend(
            "| " + " | ".join(cls._escape_table_cell(value) for value in row) + " |"
            for row in normalized[1:]
        )
        return "\n".join(lines)

    @staticmethod
    def _escape_table_cell(value: str) -> str:
        return str(value or "").replace("|", "\\|").strip()

    @staticmethod
    def _cell_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()
