"""文件解析：把 PDF / Word / Excel / 文本统一转成 Markdown。

设计要点：**解析器只负责产出 Markdown 文本**，之后走与粘贴文本完全相同的
切片与索引流程（`source_service.parse_source`），下游不需要知道原始格式。

对应 OpenSpec change ``training-source-selection`` 的 A2.3–A2.5，选型见 ADR-0012。
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("src.services.doc_parser")

#: 支持的扩展名 → 解析器
SUPPORTED_SUFFIXES: tuple[str, ...] = (".md", ".markdown", ".txt", ".pdf", ".docx", ".xlsx")

_QUESTION_HEADERS: tuple[str, ...] = ("题干", "题目", "问题", "question")
_OPTION_HEADERS: tuple[str, ...] = ("选项", "options", "option")
_ANSWER_HEADERS: tuple[str, ...] = ("答案", "正确答案", "answer")
_EXPLANATION_HEADERS: tuple[str, ...] = ("解析", "说明", "explanation")

# 常见的中文标题形态：「第三章 …」「3.2 …」
_HEADING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^第[一二三四五六七八九十百零\d]+[章节讲篇部分]\s*\S"),
    re.compile(r"^\d+(\.\d+)*[\s、\.]\s*\S"),
)


class UnsupportedFormatError(ValueError):
    """扩展名不在支持范围内。"""


def _suffix_of(filename: str | None) -> str:
    return Path(filename or "").suffix.lower()


def _looks_like_heading(line: str) -> bool:
    text = line.strip()
    if not text or len(text) > 40:
        return False
    if text.endswith(("。", "！", "？", "，", "；", "：")):
        return False
    return any(pattern.match(text) for pattern in _HEADING_PATTERNS)


def _is_title_candidate(text: str) -> bool:
    """判断一行是否像该页的标题：长度适中、结尾无标点、且含足够多的实义字符。"""
    candidate = text.strip().strip("\u200b\u200c\u200d\ufeff")
    if not (4 <= len(candidate) <= 24):
        return False
    if candidate.endswith(("。", "，", "；", "：", "！", "？", "、", ".", ",")):
        return False
    # 至少要有两个汉字或字母，过滤掉「4.」「- 1」这类列表编号
    meaningful = re.findall(r"[\u4e00-\u9fffA-Za-z]", candidate)
    return len(meaningful) >= 2


def parse_text(filename: str | None, data: bytes) -> str:
    """Markdown / 纯文本：尝试 UTF-8，失败则忽略不可解码字节。"""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("parse_text: %s 不是 UTF-8，已忽略不可解码部分", filename)
        return data.decode("utf-8", errors="ignore")


def parse_pdf(filename: str | None, data: bytes) -> str:
    """PDF：按页抽取文本，并把疑似标题的行提升为 Markdown 标题。

    每页标题取「第一个像标题的短行」，找不到才退回「第 N 页」——
    因为下游把标题当知识点名，全是「第 N 页」会让知识点失去意义。
    """
    import fitz  # pymupdf

    pieces: list[str] = []
    with fitz.open(stream=io.BytesIO(data), filetype="pdf") as doc:
        for page_index, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            if not text.strip():
                continue
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            title = ""
            for candidate in lines[:3]:
                if _is_title_candidate(candidate):
                    title = candidate.strip("\u200b\u200c\u200d\ufeff")
                    break
            # 有标题时带上页码便于溯源；没有标题就只用页码，避免「第 2 页（第 2 页）」
            heading = f"{title}（第 {page_index} 页）" if title else f"第 {page_index} 页"
            pieces.append(f"# {heading}")
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line:
                    pieces.append("")
                    continue
                if line == title:
                    continue
                if _looks_like_heading(line):
                    pieces.append(f"## {line}")
                else:
                    pieces.append(line)
            pieces.append("")
    result = "\n".join(pieces).strip()
    if not result:
        raise ValueError("PDF 没有可抽取的文本（可能是扫描件，需要 OCR）")
    return result


def parse_docx(filename: str | None, data: bytes) -> str:
    """Word：按标题样式映射 Markdown 标题层级。"""
    import docx

    document = docx.Document(io.BytesIO(data))
    pieces: list[str] = []
    for paragraph in document.paragraphs:
        text = (paragraph.text or "").strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
        level = 0
        if style.startswith("heading"):
            digits = re.findall(r"\d+", style)
            level = int(digits[0]) if digits else 1
            level = min(max(level, 1), 6)
        elif style.startswith("title"):
            level = 1
        pieces.append(f"{'#' * level} {text}" if level else text)
    result = "\n\n".join(pieces).strip()
    if not result:
        raise ValueError("Word 文档没有可读取的段落")
    return result


def _match_header(header: str, candidates: tuple[str, ...]) -> bool:
    lowered = (header or "").strip().lower()
    return any(candidate.lower() in lowered for candidate in candidates)


def parse_xlsx(filename: str | None, data: bytes) -> str:
    """Excel 题库：按表头语义解析成结构化题目，而不是当普通表格切片。

    识别失败（找不到题干列）时抛错并提示调整表头，**不猜列含义**。
    """
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    pieces: list[str] = []
    for sheet in workbook.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            continue
        header = [str(cell).strip() if cell is not None else "" for cell in rows[0]]
        index_of: dict[str, int] = {}
        for position, name in enumerate(header):
            if _match_header(name, _QUESTION_HEADERS):
                index_of.setdefault("question", position)
            elif _match_header(name, _OPTION_HEADERS):
                index_of.setdefault("options", position)
            elif _match_header(name, _ANSWER_HEADERS):
                index_of.setdefault("answer", position)
            elif _match_header(name, _EXPLANATION_HEADERS):
                index_of.setdefault("explanation", position)

        if "question" not in index_of:
            raise ValueError(
                f"工作表「{sheet.title}」找不到题干列，请在表头写明「题干」或「题目」"
            )

        pieces.append(f"# {sheet.title}")
        for number, row in enumerate(rows[1:], start=1):
            def cell(key: str) -> str:
                position = index_of.get(key)
                if position is None or position >= len(row):
                    return ""
                value = row[position]
                return "" if value is None else str(value).strip()

            question = cell("question")
            if not question:
                continue
            pieces.append(f"## 题目 {number}")
            pieces.append(f"**题干**：{question}")
            options = cell("options")
            if options:
                pieces.append(f"**选项**：{options}")
            answer = cell("answer")
            if answer:
                pieces.append(f"**正确答案**：{answer}")
            explanation = cell("explanation")
            if explanation:
                pieces.append(f"**解析**：{explanation}")
            pieces.append("")

    result = "\n".join(pieces).strip()
    if not result:
        raise ValueError("Excel 里没有可解析的题目")
    return result


_PARSERS: dict[str, Any] = {
    ".md": parse_text,
    ".markdown": parse_text,
    ".txt": parse_text,
    ".pdf": parse_pdf,
    ".docx": parse_docx,
    ".xlsx": parse_xlsx,
}


def parse_file(filename: str, data: bytes) -> str:
    """按扩展名分发解析，返回 Markdown 文本。"""
    suffix = _suffix_of(filename)
    parser = _PARSERS.get(suffix)
    if parser is None:
        raise UnsupportedFormatError(
            f"暂不支持 {suffix or '该'} 格式（支持：{'、'.join(SUPPORTED_SUFFIXES)}）"
        )
    return parser(filename, data)


__all__ = [
    "SUPPORTED_SUFFIXES",
    "UnsupportedFormatError",
    "parse_docx",
    "parse_file",
    "parse_pdf",
    "parse_text",
    "parse_xlsx",
]
