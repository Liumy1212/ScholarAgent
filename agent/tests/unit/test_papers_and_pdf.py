import asyncio
from pathlib import Path

import pymupdf
import pytest
from tests.support import MemoryUpload, RecordingVectorStore, runtime_settings, sqlite_database

from airesearcher_agent.application.errors import AgentError, IngestionError
from airesearcher_agent.application.papers import PaperService
from airesearcher_agent.ingestion.pdf import PdfParser


def _write_text_pdf(path: Path) -> None:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    first = document.new_page()
    first.insert_text(
        (72, 72),
        "Page one: bilingual retrieval evidence. 第一页包含检索证据。" * 4,
        fontname="china-s",
        fontsize=11,
    )
    second = document.new_page()
    second.insert_text(
        (72, 72),
        "Page two: the control group improved by 17 percent. 第二页是实验结论。" * 4,
        fontname="china-s",
        fontsize=11,
    )
    document.set_metadata(
        {
            "title": "Synthetic bilingual paper",
            "author": "Ada Example; 李明",
            "creationDate": "D:20260825000000+08'00'",
        }
    )
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]


def _write_blank_pdf(path: Path) -> None:
    document = pymupdf.open()  # type: ignore[no-untyped-call]
    document.new_page()
    document.save(path)  # type: ignore[no-untyped-call]
    document.close()  # type: ignore[no-untyped-call]


def test_upload_streams_to_external_storage_and_sha256_deduplicates(tmp_path: Path) -> None:
    settings = runtime_settings(tmp_path)
    database = sqlite_database()
    vectors = RecordingVectorStore()
    service = PaperService(database=database, settings=settings, vector_store=vectors)
    content = b"%PDF-1.7\nsynthetic redistributable test bytes"

    first = asyncio.run(service.upload(MemoryUpload(content, filename="research.pdf")))
    second = asyncio.run(service.upload(MemoryUpload(content, filename="copy.pdf")))

    assert first.duplicate is False
    assert second.duplicate is True
    assert second.paper.paper_id == first.paper.paper_id
    stored = service.get_file(first.paper.paper_id)
    assert Path(stored.path).is_relative_to(settings.storage_dir / "papers")
    assert Path(stored.path).read_bytes() == content
    assert len(list((settings.storage_dir / "papers").glob("*.pdf"))) == 1


@pytest.mark.parametrize(
    ("upload", "expected_code"),
    [
        (MemoryUpload(b"not a pdf"), "INVALID_PDF"),
        (MemoryUpload(b"%PDF-test", content_type="text/plain"), "UNSUPPORTED_MEDIA_TYPE"),
        (MemoryUpload(b"%PDF-test", filename="paper.txt"), "UNSUPPORTED_MEDIA_TYPE"),
    ],
)
def test_upload_rejects_invalid_pdf_inputs(
    tmp_path: Path,
    upload: MemoryUpload,
    expected_code: str,
) -> None:
    service = PaperService(
        database=sqlite_database(),
        settings=runtime_settings(tmp_path),
        vector_store=RecordingVectorStore(),
    )

    with pytest.raises(AgentError) as captured:
        asyncio.run(service.upload(upload))

    assert captured.value.code == expected_code


def test_parser_keeps_chunks_on_their_source_page_and_extracts_metadata(tmp_path: Path) -> None:
    pdf_path = tmp_path / "two-pages.pdf"
    _write_text_pdf(pdf_path)
    parser = PdfParser(max_pages=500, chunk_size=200, chunk_overlap=30)

    parsed = parser.parse(paper_id="paper-test", path=pdf_path)

    assert parsed.page_count == 2
    assert parsed.title == "Synthetic bilingual paper"
    assert parsed.publication_year == 2026
    assert set(chunk.page for chunk in parsed.chunks) == {1, 2}
    assert all(chunk.paper_id == "paper-test" for chunk in parsed.chunks)
    assert all(chunk.quote == chunk.text for chunk in parsed.chunks)
    assert len({chunk.chunk_id for chunk in parsed.chunks}) == len(parsed.chunks)
    assert parser.parse(paper_id="paper-test", path=pdf_path).chunks == parsed.chunks


def test_parser_rejects_pdf_without_extractable_text(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank.pdf"
    _write_blank_pdf(pdf_path)

    with pytest.raises(IngestionError) as captured:
        PdfParser(max_pages=500, chunk_size=200, chunk_overlap=20).parse(
            paper_id="paper-blank",
            path=pdf_path,
        )

    assert captured.value.code == "PDF_HAS_NO_TEXT"
