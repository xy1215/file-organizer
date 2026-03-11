from __future__ import annotations

import csv
from pathlib import Path

import fitz
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation


class UnsupportedSummaryError(Exception):
    pass


def _limit_text(text: str, max_chars: int = 3000) -> str:
    cleaned = text.strip()
    return cleaned[:max_chars]


def extract_pdf_text(file_path: Path) -> str:
    chunks: list[str] = []
    with fitz.open(file_path) as doc:
        for page_index in range(min(len(doc), 10)):
            chunks.append(doc[page_index].get_text("text"))
    return "\n".join(chunks).strip()


def extract_docx_text(file_path: Path) -> str:
    doc = Document(file_path)
    parts = [paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip()]
    return _limit_text("\n".join(parts), 3000)


def extract_xlsx_text(file_path: Path) -> str:
    workbook = load_workbook(file_path, read_only=True, data_only=True)
    parts: list[str] = []
    for sheet in workbook.worksheets:
        parts.append(f"Sheet: {sheet.title}")
        for row_index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            if row_index > 20:
                break
            values = [str(cell) if cell is not None else "" for cell in row]
            parts.append(" | ".join(values))
    workbook.close()
    return "\n".join(parts).strip()


def extract_pptx_text(file_path: Path) -> str:
    presentation = Presentation(file_path)
    parts: list[str] = []
    for index, slide in enumerate(presentation.slides, start=1):
        parts.append(f"Slide {index}")
        for shape in slide.shapes:
            if hasattr(shape, "text") and str(shape.text).strip():
                parts.append(str(shape.text).strip())
    return "\n".join(parts).strip()


def extract_text_text(file_path: Path) -> str:
    return _limit_text(file_path.read_text(encoding="utf-8", errors="ignore"), 3000)


def extract_csv_text(file_path: Path) -> str:
    with file_path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
        reader = csv.reader(handle)
        rows = [", ".join(row) for row in reader]
    return _limit_text("\n".join(rows), 3000)


def extract_text(file_path: str) -> str:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_text(path)
    if suffix == ".docx":
        return extract_docx_text(path)
    if suffix == ".xlsx":
        return extract_xlsx_text(path)
    if suffix == ".pptx":
        return extract_pptx_text(path)
    if suffix in {".txt", ".md"}:
        return extract_text_text(path)
    if suffix == ".csv":
        return extract_csv_text(path)
    if suffix in {".doc", ".xls", ".ppt"}:
        raise UnsupportedSummaryError("旧版 Office 文件暂不支持自动提取正文，请先转换为新版格式。")
    raise UnsupportedSummaryError(f"暂不支持此文件类型的摘要提取：{suffix}")
