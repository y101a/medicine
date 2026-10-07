"""PDF image OCR stays local and never claims table-cell alignment."""

import io
import subprocess

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from app.services import document_extract_worker as worker


def pdf_with_image(*, with_text: bool = False) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    image = Image.new("RGB", (100, 100), "white")
    image_stream = DecodedStreamObject()
    image_stream.set_data(image.tobytes())
    image_stream.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(100),
            NameObject("/Height"): NumberObject(100),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    resources = DictionaryObject(
        {
            NameObject("/XObject"): DictionaryObject(
                {NameObject("/Im1"): writer._add_object(image_stream)}
            )
        }
    )
    commands = [b"q 100 0 0 100 72 600 cm /Im1 Do Q"]
    if with_text:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        resources[NameObject("/Font")] = DictionaryObject(
            {NameObject("/F1"): writer._add_object(font)}
        )
        commands.append(b"BT /F1 12 Tf 72 720 Td (Visible text) Tj ET")
    page[NameObject("/Resources")] = resources
    content = DecodedStreamObject()
    content.set_data(b"\n".join(commands))
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_image_only_pdf_requires_local_engine(monkeypatch):
    monkeypatch.setattr(worker, "find_tesseract", lambda: None)
    with pytest.raises(worker.ParseFailure) as error:
        worker.parse_pdf(pdf_with_image(), 10)
    assert error.value.code == "FILE_OCR_UNAVAILABLE"


def test_mixed_pdf_keeps_text_and_explains_unread_image(monkeypatch):
    monkeypatch.setattr(worker, "find_tesseract", lambda: None)
    sections, tables, pages = worker.parse_pdf(pdf_with_image(with_text=True), 10)
    assert pages == 1 and tables == []
    assert any("Visible text" in section.text for section in sections)
    assert any("图片文字未读取" in section.text for section in sections)


def test_local_image_ocr_is_marked_unverified(monkeypatch):
    monkeypatch.setattr(worker.shutil, "which", lambda _name: "tesseract")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "--list-langs" in command:
            return subprocess.CompletedProcess(
                command, 0, b"List of available languages:\nchi_sim\neng\n", b""
            )
        assert command == ["tesseract", "stdin", "stdout", "-l", "chi_sim+eng"]
        assert kwargs["input"].startswith(b"\x89PNG")
        return subprocess.CompletedProcess(command, 0, "白细胞 6.2".encode(), b"")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    sections, tables, pages = worker.parse_pdf(pdf_with_image(), 10)
    assert pages == 1 and tables == []
    assert any(
        "图片 OCR 自动转录" in section.text and "白细胞 6.2" in section.text
        for section in sections
    )
    assert any("表格行列及单位对应未验证" in section.text for section in sections)
    assert len(calls) == 2


def test_missing_chinese_language_pack_is_unavailable(monkeypatch):
    monkeypatch.setattr(worker.shutil, "which", lambda _name: "tesseract")
    monkeypatch.setattr(
        worker.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, b"eng\n", b""),
    )
    with pytest.raises(worker.ParseFailure) as error:
        worker.parse_pdf(pdf_with_image(), 10)
    assert error.value.code == "FILE_OCR_UNAVAILABLE"


def test_image_only_pdf_with_empty_ocr_is_not_saved_as_a_warning(monkeypatch):
    monkeypatch.setattr(worker.shutil, "which", lambda _name: "tesseract")

    def fake_run(command, **kwargs):
        if "--list-langs" in command:
            return subprocess.CompletedProcess(command, 0, b"chi_sim\neng\n", b"")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    with pytest.raises(worker.ParseFailure) as error:
        worker.parse_pdf(pdf_with_image(), 10)
    assert error.value.code == "FILE_NO_TEXT"


def test_ocr_timeout_does_not_erase_existing_pdf_text(monkeypatch):
    monkeypatch.setattr(worker.shutil, "which", lambda _name: "tesseract")

    def fake_run(command, **kwargs):
        if "--list-langs" in command:
            return subprocess.CompletedProcess(command, 0, b"chi_sim\neng\n", b"")
        raise subprocess.TimeoutExpired(command, 3)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    sections, tables, _ = worker.parse_pdf(pdf_with_image(with_text=True), 10)
    assert tables == []
    assert any("Visible text" in section.text for section in sections)
