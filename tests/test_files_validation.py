from __future__ import annotations

import pytest

from app.common.files import validate_upload
from tests.helpers import jpeg_bytes, pdf_bytes, png_bytes, xlsx_bytes


@pytest.mark.parametrize(
    ("data", "filename", "content_type"),
    [
        (png_bytes(), "image.PNG", "image/png"),
        (jpeg_bytes(), "photo.jpg", "image/jpeg"),
        (jpeg_bytes(), "photo.jpeg", "image/jpeg"),
        (pdf_bytes(), "document.pdf", "application/pdf"),
        (
            xlsx_bytes(),
            "table.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (b"hello", "notes.txt", "text/plain; charset=utf-8"),
        (b"a,b\n1,2\n", "data.csv", "text/csv; charset=utf-8"),
    ],
)
def test_validate_supported_content(data: bytes, filename: str, content_type: str) -> None:
    result = validate_upload(data, filename)
    assert result.content_type == content_type
    assert result.filename == filename


@pytest.mark.parametrize(
    ("data", "filename"),
    [
        (b"not really a PDF", "fake.pdf"),
        (b"\x89PNG\r\n\x1a\n" + b"broken", "fake.png"),
        (b"GIF89a", "wrong.jpg"),
        (xlsx_bytes(formula=True), "formula.xlsx"),
        (b"binary\x00text", "binary.txt"),
        (b"not-utf8-\xff", "bad.csv"),
        (b"hello", "../escape.txt"),
        (b"hello", "line\nbreak.txt"),
    ],
)
def test_validate_rejects_content_or_filename_confusion(data: bytes, filename: str) -> None:
    with pytest.raises(ValueError):
        validate_upload(data, filename)


def test_validate_rejects_oversized_upload() -> None:
    with pytest.raises(ValueError):
        validate_upload(png_bytes(), "image.png", max_bytes=8)
