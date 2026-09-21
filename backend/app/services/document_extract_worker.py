"""Isolated document parser worker.

The parent process sends bounded bytes over stdin and kills this process on timeout.
Only JSON metadata and extracted text are written to stdout; input bytes are never written to disk.
"""

import argparse
import io
import json
import re
import sys
import zipfile
from dataclasses import asdict, dataclass

from docx import Document
from pptx import Presentation
from pypdf import PdfReader

MAX_ZIP_ENTRIES = 2_000
MAX_ZIP_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 20 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 100


@dataclass(frozen=True)
class Section:
    locator: str
    text: str


class ParseFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def fail(code: str, message: str) -> None:
    raise ParseFailure(code, message)


def normalize_text(value: str) -> str:
    value = value.replace("\x00", " ")
    value = re.sub(r"[\u0001-\u0008\u000b\u000c\u000e-\u001f\u007f]", " ", value)
    value = re.sub(r"[ \t\u3000]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def inspect_ooxml(content: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if not infos or len(infos) > MAX_ZIP_ENTRIES:
                fail("FILE_ZIP_UNSAFE", "文档压缩结构不安全")
            total = 0
            names: set[str] = set()
            for info in infos:
                name = info.filename.replace("\\", "/")
                path_parts = [part for part in name.split("/") if part]
                if (
                    name.startswith("/")
                    or ".." in path_parts
                    or name.casefold().endswith("vbaproject.bin")
                    or name in names
                    or info.flag_bits & 0x1
                ):
                    fail("FILE_ZIP_UNSAFE", "文档压缩结构不安全")
                names.add(name)
                total += info.file_size
                if info.file_size > MAX_ZIP_MEMBER_BYTES or total > MAX_ZIP_UNCOMPRESSED_BYTES:
                    fail("FILE_ZIP_UNSAFE", "文档解压后内容过大")
                if info.compress_size == 0:
                    if info.file_size > 0:
                        fail("FILE_ZIP_UNSAFE", "文档压缩比异常")
                elif info.file_size / info.compress_size > MAX_ZIP_COMPRESSION_RATIO:
                    fail("FILE_ZIP_UNSAFE", "文档压缩比异常")
            if "[Content_Types].xml" not in names:
                fail("FILE_TYPE_NOT_ALLOWED", "仅支持 PDF、DOCX、PPTX、TXT 和 Markdown")
            if "word/document.xml" in names:
                return "docx"
            if "ppt/presentation.xml" in names:
                return "pptx"
    except ParseFailure:
        raise
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise ParseFailure("FILE_PARSE_FAILED", "文档已损坏或无法解析") from exc
    fail("FILE_TYPE_NOT_ALLOWED", "仅支持 PDF、DOCX、PPTX、TXT 和 Markdown")


def detect_kind(content: bytes, extension: str) -> str:
    if content.startswith(b"%PDF-"):
        return "pdf"
    if content.startswith(b"PK\x03\x04"):
        return inspect_ooxml(content)
    if content.startswith(b"\xd0\xcf\x11\xe0"):
        fail("FILE_TYPE_NOT_ALLOWED", "暂不支持旧版 DOC/PPT 或宏格式文档")
    try:
        content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseFailure(
            "FILE_TYPE_NOT_ALLOWED",
            "TXT 和 Markdown 文件必须使用 UTF-8 编码",
        ) from exc
    if b"\x00" in content:
        fail("FILE_TYPE_NOT_ALLOWED", "仅支持 PDF、DOCX、PPTX、TXT 和 Markdown")
    return "md" if extension == ".md" else "txt"


def parse_pdf(content: bytes, max_pages: int) -> tuple[list[Section], int]:
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if reader.is_encrypted:
            fail("FILE_ENCRYPTED", "暂不支持加密 PDF")
        page_count = len(reader.pages)
        if page_count > max_pages:
            fail("FILE_PAGE_LIMIT", f"PDF 最多支持 {max_pages} 页")
        sections = []
        for index, page in enumerate(reader.pages, start=1):
            text = normalize_text(page.extract_text() or "")
            if text:
                sections.append(Section(f"第 {index} 页", text))
        return sections, page_count
    except ParseFailure:
        raise
    except Exception as exc:
        raise ParseFailure("FILE_PARSE_FAILED", "PDF 已损坏或无法解析") from exc


def parse_docx(content: bytes) -> tuple[list[Section], None]:
    try:
        document = Document(io.BytesIO(content))
        sections: list[Section] = []
        position = 1
        for paragraph in document.paragraphs:
            text = normalize_text(paragraph.text)
            if text:
                sections.append(Section(f"第 {position} 段", text))
                position += 1
        for table_index, table in enumerate(document.tables, start=1):
            rows = []
            for row in table.rows:
                cells = [normalize_text(cell.text) for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                sections.append(Section(f"表格 {table_index}", "\n".join(rows)))
        return sections, None
    except Exception as exc:
        raise ParseFailure("FILE_PARSE_FAILED", "DOCX 已损坏或无法解析") from exc


def parse_pptx(content: bytes, max_pages: int) -> tuple[list[Section], int]:
    try:
        presentation = Presentation(io.BytesIO(content))
        page_count = len(presentation.slides)
        if page_count > max_pages:
            fail("FILE_PAGE_LIMIT", f"PPTX 最多支持 {max_pages} 张幻灯片")
        sections = []
        for index, slide in enumerate(presentation.slides, start=1):
            parts = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    text = normalize_text(shape.text)
                    if text:
                        parts.append(text)
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        cells = [normalize_text(cell.text) for cell in row.cells]
                        if any(cells):
                            parts.append(" | ".join(cells))
            if parts:
                sections.append(Section(f"第 {index} 张幻灯片", "\n".join(parts)))
        return sections, page_count
    except ParseFailure:
        raise
    except Exception as exc:
        raise ParseFailure("FILE_PARSE_FAILED", "PPTX 已损坏或无法解析") from exc


def parse_text(content: bytes) -> tuple[list[Section], None]:
    text = normalize_text(content.decode("utf-8-sig"))
    blocks = [normalize_text(block) for block in re.split(r"\n\s*\n", text)]
    sections = [
        Section(f"第 {index} 段", block)
        for index, block in enumerate((item for item in blocks if item), start=1)
    ]
    return sections, None


def parse(content: bytes, extension: str, max_pages: int, max_chars: int) -> dict[str, object]:
    kind = detect_kind(content, extension)
    allowed_extensions = {
        "pdf": {".pdf"},
        "docx": {".docx"},
        "pptx": {".pptx"},
        "txt": {".txt"},
        "md": {".md"},
    }
    if extension not in allowed_extensions[kind]:
        fail("FILE_TYPE_NOT_ALLOWED", "文件扩展名与实际内容类型不一致")
    if kind == "pdf":
        sections, page_count = parse_pdf(content, max_pages)
    elif kind == "docx":
        sections, page_count = parse_docx(content)
    elif kind == "pptx":
        sections, page_count = parse_pptx(content, max_pages)
    else:
        sections, page_count = parse_text(content)
    char_count = sum(len(section.text) for section in sections)
    if char_count == 0:
        fail("FILE_NO_TEXT", "文档像是扫描件或没有可读取文字，暂时无法解析")
    if char_count > max_chars:
        fail("FILE_TEXT_TOO_LARGE", "文档文字过多，请拆分原文件后重试")
    return {
        "ok": True,
        "kind": kind,
        "pageCount": page_count,
        "charCount": char_count,
        "sections": [asdict(section) for section in sections],
    }


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--extension", required=True)
    parser.add_argument("--max-pages", type=int, required=True)
    parser.add_argument("--max-chars", type=int, required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    args = parser.parse_args()
    content = sys.stdin.buffer.read(args.max_bytes + 1)
    try:
        if not content:
            fail("FILE_PARSE_FAILED", "文档内容为空")
        if len(content) > args.max_bytes:
            fail("FILE_TOO_LARGE", "单个文档不能超过 10 MB")
        result = parse(content, args.extension.lower(), args.max_pages, args.max_chars)
    except ParseFailure as exc:
        result = {"ok": False, "code": exc.code, "message": exc.message}
    except Exception:
        result = {"ok": False, "code": "FILE_PARSE_FAILED", "message": "文档无法解析"}
    # Keep the worker protocol ASCII-only so Windows console code pages cannot
    # corrupt JSON exchanged over the subprocess pipe.
    sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
