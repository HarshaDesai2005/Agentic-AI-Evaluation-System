from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from models.schemas import DocumentCategory, ExtractedDocument, ExtractedPage
from services.document_processor import extract_document, merge_extracted
from services.security_service import sha256_bytes, validate_upload


def _text_png(path: Path, text: str = "Q1 Explain Boolean algebra. (5 marks)") -> Path:
    image = Image.new("RGB", (900, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 70), text, fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path


def _photo_pdf(path: Path, image_path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawImage(ImageReader(str(image_path)), 40, 500, width=500, height=120)
    c.save()
    return path


def test_accepts_png_and_rejects_fake_image():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    assert validate_upload("page.png", png) is None
    assert validate_upload("page.jpg", b"not-an-image") 


def test_image_without_tesseract_reports_setup(tmp_path, monkeypatch):
    png = _text_png(tmp_path / "page.png")
    with patch("services.document_processor._resolve_tesseract", return_value=(None, "Tesseract OCR is required")):
        doc = extract_document(
            png, "page.png", DocumentCategory.QUESTION_PAPER, sha256_bytes(png.read_bytes())
        )
    assert doc.extraction_status == "ocr_unavailable"
    assert doc.empty
    assert "Tesseract" in (doc.extraction_error or "")


def test_image_ocr_with_stub(tmp_path):
    png = _text_png(tmp_path / "page.png")
    with patch("services.document_processor._ocr_pil_image", return_value=("Q1 Explain Boolean algebra. (5 marks)", True, None)):
        doc = extract_document(
            png, "page.png", DocumentCategory.QUESTION_PAPER, sha256_bytes(png.read_bytes())
        )
    assert not doc.empty
    assert doc.ocr_used
    assert "Boolean" in doc.full_text
    assert doc.page_count == 1


def test_photo_pdf_ocr_when_native_text_missing(tmp_path):
    png = _text_png(tmp_path / "snap.png")
    pdf = _photo_pdf(tmp_path / "scan.pdf", png)
    with patch(
        "services.document_processor._ocr_pil_image",
        return_value=("Q2 Convert 101101 to decimal. (5 marks)", True, None),
    ):
        doc = extract_document(
            pdf,
            "scan.pdf",
            DocumentCategory.QUESTION_PAPER,
            sha256_bytes(pdf.read_bytes()),
            allow_ocr=True,
        )
    assert doc.ocr_used
    assert "101101" in doc.full_text


def test_merge_photo_pages():
    one = ExtractedDocument(
        original_filename="p1.png",
        stored_filename="p1.png",
        file_type=".png",
        category=DocumentCategory.QUESTION_PAPER,
        page_count=1,
        pages=[ExtractedPage(page_number=1, text="Q1 First page")],
        full_text="Q1 First page",
        ocr_used=True,
        sha256="a",
    )
    two = ExtractedDocument(
        original_filename="p2.png",
        stored_filename="p2.png",
        file_type=".png",
        category=DocumentCategory.QUESTION_PAPER,
        page_count=1,
        pages=[ExtractedPage(page_number=1, text="Q2 Second page")],
        full_text="Q2 Second page",
        ocr_used=True,
        sha256="b",
    )
    merged = merge_extracted([one, two], original_filename="paper photos")
    assert merged.page_count == 2
    assert merged.pages[0].page_number == 1
    assert merged.pages[1].page_number == 2
    assert "First page" in merged.full_text and "Second page" in merged.full_text
