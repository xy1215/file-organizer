from __future__ import annotations

import codecs

import pytest
from openpyxl import Workbook

import summarizer
from summarizer import UnsupportedSummaryError, _decode_text_bytes, extract_text


TEXT = "会议纪要：讨论第三季度预算安排"


@pytest.mark.parametrize(
    "encoded",
    [
        TEXT.encode("utf-8"),
        codecs.BOM_UTF8 + TEXT.encode("utf-8"),
        TEXT.encode("gbk"),
        TEXT.encode("utf-16"),
    ],
    ids=["utf8", "utf8-bom", "gbk", "utf16-bom"],
)
def test_extract_txt_detects_encoding(tmp_path, encoded):
    path = tmp_path / "note.txt"
    path.write_bytes(encoded)
    assert extract_text(str(path)) == TEXT


def test_decode_tolerates_truncated_multibyte_character():
    data = TEXT.encode("utf-8")
    # Cut in the middle of the last 3-byte character: still recognised as UTF-8, not GB18030.
    assert _decode_text_bytes(data[:-1], complete=False) == TEXT[:-1]


def test_extract_txt_reads_large_utf8_file(tmp_path, monkeypatch):
    monkeypatch.setattr(summarizer, "_TEXT_SNIFF_BYTES", 100)
    path = tmp_path / "big.md"
    path.write_text("中" * 1000, encoding="utf-8")
    text = extract_text(str(path))
    assert text and set(text) == {"中"}


def test_extract_csv_gbk(tmp_path):
    path = tmp_path / "data.csv"
    path.write_bytes("姓名,金额\n张三,100\n\n李四,200\n".encode("gbk"))
    assert extract_text(str(path)) == "姓名, 金额\n张三, 100\n李四, 200"


def test_extract_xlsx_skips_blank_cells_and_rows(tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "预算"
    sheet["A1"] = "项目"
    sheet["B1"] = "金额"
    sheet["A5"] = "差旅"
    sheet["B5"] = 1200
    sheet["F5"] = ""
    path = tmp_path / "budget.xlsx"
    workbook.save(path)
    assert extract_text(str(path)) == "Sheet: 预算\n项目 | 金额\n差旅 | 1200"


def test_extract_unsupported_type(tmp_path):
    path = tmp_path / "a.xyz"
    path.write_text("x")
    with pytest.raises(UnsupportedSummaryError) as info:
        extract_text(str(path))
    assert info.value.code == "unsupported_type"


@pytest.mark.parametrize("text", ["季度报告：收入增长，成本下降。", "合同", "简历-王小明-2024"])
def test_utf8_with_a_stray_byte_is_not_decoded_as_gb18030(text):
    assert _decode_text_bytes(text.encode("utf-8") + b"\x80", complete=True) == text


@pytest.mark.parametrize("text", ["合同", "发票", "姓名,金额\n张三,100", "《红楼梦》读书笔记——第一回"])
def test_short_gbk_is_still_detected(text):
    assert _decode_text_bytes(text.encode("gbk"), complete=True) == text
