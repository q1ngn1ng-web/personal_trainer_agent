"""资料来源的领域逻辑：切片、校验值、影响面。

纯函数，不依赖数据库与 LLM。
对应 OpenSpec change ``training-source-selection`` 的阶段 A。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

#: 单个切片的目标上限；超过则递归按段落再切
DEFAULT_MAX_CHARS: int = 1200

#: 支持的来源类型
SOURCE_TYPES: tuple[str, ...] = ("ai_generated", "user_upload", "user_paste", "web_url")

#: 解析状态
PARSE_STATUSES: tuple[str, ...] = ("pending", "ok", "failed", "unsupported")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    """切好的一段内容。"""

    ordinal: int
    heading_path: str
    text: str

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class ImpactReport:
    """同一来源内容变化后的影响面。"""

    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": list(self.added),
            "removed": list(self.removed),
            "changed": list(self.changed),
        }


def content_checksum(text: str) -> str:
    """内容指纹，用于判断是否需要重新解析。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _split_long(text: str, max_chars: int) -> list[str]:
    """把超长文本按段落切；单段仍超长时按长度硬切。"""
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    buffer = ""
    for paragraph in text.split("\n\n"):
        candidate = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if len(candidate) <= max_chars:
            buffer = candidate
            continue
        if buffer:
            pieces.append(buffer)
        while len(paragraph) > max_chars:
            pieces.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]
        buffer = paragraph
    if buffer:
        pieces.append(buffer)
    return [piece for piece in pieces if piece.strip()]


def split_markdown(text: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    """按标题层级与段落边界切片。

    规则：标题改变层级时先落盘已积累的内容；超长内容递归切分并**保留标题前缀**。
    标题栈**按层级维护**——同级标题是兄弟而不是父子，否则会出现
    「A > B > C」这种把并列小节串成链条的错误路径。
    """
    chunks: list[Chunk] = []
    stack: list[tuple[int, str]] = []
    buffer: list[str] = []
    ordinal = 0

    def flush() -> None:
        nonlocal ordinal, buffer
        body = "\n\n".join(part for part in buffer if part.strip()).strip()
        buffer = []
        if not body:
            return
        heading = " > ".join(title for _, title in stack) if stack else "（未分节）"
        for piece in _split_long(body, max_chars):
            chunks.append(Chunk(ordinal=ordinal, heading_path=heading, text=piece))
            ordinal += 1

    for raw_line in (text or "").splitlines():
        match = _HEADING_RE.match(raw_line.strip())
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            continue
        buffer.append(raw_line)
    flush()
    return chunks


def chunk_keys(chunks: Iterable[Chunk]) -> dict[str, str]:
    """用「标题路径 + 内容指纹」标识一个切片，用于比对前后差异。"""
    return {f"{chunk.heading_path}#{content_checksum(chunk.text)}": chunk.text for chunk in chunks}


def compute_impact(old_chunks: Iterable[Chunk], new_chunks: Iterable[Chunk]) -> ImpactReport:
    """比较两次解析的切片集合，给出新增 / 删除 / 修改清单。

    以「标题路径」为对齐键：同一路径下内容变了算修改，只在一侧出现算新增或删除。
    """
    old_map: dict[str, str] = {}
    for chunk in old_chunks:
        old_map.setdefault(chunk.heading_path, chunk.text)
    new_map: dict[str, str] = {}
    for chunk in new_chunks:
        new_map.setdefault(chunk.heading_path, chunk.text)

    added = [key for key in new_map if key not in old_map]
    removed = [key for key in old_map if key not in new_map]
    changed = [
        key
        for key, value in new_map.items()
        if key in old_map and content_checksum(old_map[key]) != content_checksum(value)
    ]
    return ImpactReport(added=sorted(added), removed=sorted(removed), changed=sorted(changed))


def validate_source_type(source_type: str) -> str:
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"unknown source type: {source_type!r}")
    return source_type


def sanitize_chunk_ids(ids: Iterable[Any], existing: set[int]) -> tuple[list[int], list[int]]:
    """校验切片回指：返回（有效 ID, 被丢弃的 ID）。"""
    valid: list[int] = []
    dropped: list[int] = []
    for raw in ids or []:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value in existing:
            valid.append(value)
        else:
            dropped.append(value)
    return valid, dropped


__all__ = [
    "DEFAULT_MAX_CHARS",
    "PARSE_STATUSES",
    "SOURCE_TYPES",
    "Chunk",
    "ImpactReport",
    "chunk_keys",
    "compute_impact",
    "content_checksum",
    "sanitize_chunk_ids",
    "split_markdown",
    "validate_source_type",
]
