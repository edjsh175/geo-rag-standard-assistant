from __future__ import annotations

import json

import pytest

from app.services.document_text_extractor import (
    DocumentTextExtractor,
    UnsupportedDocumentParser,
)


def test_text_extractor_reads_plain_text_markdown_csv_json_and_geojson(tmp_path) -> None:
    extractor = DocumentTextExtractor()

    txt = tmp_path / "sample.txt"
    txt.write_text("第一章 文本内容", encoding="utf-8")

    md = tmp_path / "sample.md"
    md.write_text("# 标题\n\nMarkdown 内容", encoding="utf-8")

    csv_file = tmp_path / "sample.csv"
    csv_file.write_text("name,value\n坡度,30\n", encoding="utf-8")

    json_file = tmp_path / "sample.json"
    json_file.write_text(json.dumps({"name": "规划指标", "value": 12}, ensure_ascii=False), encoding="utf-8")

    geojson = tmp_path / "sample.geojson"
    geojson.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "生态红线"},
                        "geometry": {"type": "Point", "coordinates": [106.5, 29.5]},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert extractor.extract(txt, "text/plain").text == "第一章 文本内容"
    assert "Markdown 内容" in extractor.extract(md, "text/markdown").text
    assert "坡度" in extractor.extract(csv_file, "text/csv").text
    assert "规划指标" in extractor.extract(json_file, "application/json").text
    assert "生态红线" in extractor.extract(geojson, "application/geo+json").text


def test_text_extractor_rejects_legacy_doc_with_clear_error(tmp_path) -> None:
    extractor = DocumentTextExtractor()
    doc_file = tmp_path / "legacy.doc"
    doc_file.write_bytes(b"legacy binary document")

    with pytest.raises(UnsupportedDocumentParser, match="Legacy .doc parsing is not supported"):
        extractor.extract(doc_file, "application/msword")
