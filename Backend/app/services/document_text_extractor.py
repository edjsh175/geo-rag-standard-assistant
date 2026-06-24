"""Extract text from uploaded documents for indexing."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any


class UnsupportedDocumentParser(ValueError):
    """Raised when an uploaded file can be stored but cannot be indexed."""


@dataclass(frozen=True)
class ExtractedDocumentText:
    """Normalized text extracted from one uploaded object."""

    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class DocumentTextExtractor:
    """Parse supported upload formats into plain UTF-8 text."""

    TEXT_EXTENSIONS = {".txt", ".md"}
    JSON_EXTENSIONS = {".json", ".geojson"}

    def extract(self, path: Path, content_type: str | None = None) -> ExtractedDocumentText:
        suffix = path.suffix.lower()
        normalized_content_type = (content_type or "").split(";", 1)[0].strip().lower()

        if suffix == ".doc":
            raise UnsupportedDocumentParser("Legacy .doc parsing is not supported in the indexer.")
        if suffix in self.TEXT_EXTENSIONS:
            return ExtractedDocumentText(text=self._read_text(path))
        if suffix == ".csv":
            return ExtractedDocumentText(text=self._read_csv(path))
        if suffix in self.JSON_EXTENSIONS or normalized_content_type in {"application/json", "application/geo+json"}:
            return ExtractedDocumentText(text=self._read_json(path))
        if suffix == ".pdf" or normalized_content_type == "application/pdf":
            return ExtractedDocumentText(text=self._read_pdf(path))
        if suffix == ".docx" or normalized_content_type.endswith("wordprocessingml.document"):
            return ExtractedDocumentText(text=self._read_docx(path))

        raise UnsupportedDocumentParser(f"No document parser is available for '{suffix or normalized_content_type}'.")

    @staticmethod
    def _read_text(path: Path) -> str:
        return path.read_text(encoding="utf-8").strip()

    @staticmethod
    def _read_csv(path: Path) -> str:
        lines: list[str] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for row in reader:
                lines.append(" | ".join(cell.strip() for cell in row if cell is not None))
        return "\n".join(line for line in lines if line).strip()

    @staticmethod
    def _read_json(path: Path) -> str:
        data = json.loads(path.read_text(encoding="utf-8"))
        return json.dumps(data, ensure_ascii=False, indent=2)

    @staticmethod
    def _read_pdf(path: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - depends on runtime extras
            raise UnsupportedDocumentParser("PDF parser dependency is not installed.") from exc

        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(page.strip() for page in pages if page.strip()).strip()

    @staticmethod
    def _read_docx(path: Path) -> str:
        try:
            from docx import Document as DocxDocument
        except ImportError as exc:  # pragma: no cover - depends on runtime extras
            raise UnsupportedDocumentParser("DOCX parser dependency is not installed.") from exc

        document = DocxDocument(str(path))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
        return "\n".join(paragraph for paragraph in paragraphs if paragraph).strip()
