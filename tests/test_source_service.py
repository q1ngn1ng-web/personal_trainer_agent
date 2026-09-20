"""资料来源阶段 A 的测试：切片纯函数 + 来源服务。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.source import (  # noqa: E402
    Chunk,
    compute_impact,
    content_checksum,
    sanitize_chunk_ids,
    split_markdown,
)
from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import source_service as svc  # noqa: E402

_SAMPLE_MD = """# 第三章 虚拟语气

## 3.2 虚拟语气

虚拟语气用于表达与事实相反的假设。

### 用法一

if 引导的条件句，主句用 would + 动词原形。

## 3.3 易混点

if only 与 wish 的区别。
"""


class TestSlicing(unittest.TestCase):
    def test_heading_path_nested(self) -> None:
        chunks = split_markdown(_SAMPLE_MD)
        paths = [chunk.heading_path for chunk in chunks]
        self.assertIn("第三章 虚拟语气 > 3.2 虚拟语气", paths)
        self.assertIn("第三章 虚拟语气 > 3.2 虚拟语气 > 用法一", paths)
        self.assertIn("第三章 虚拟语气 > 3.3 易混点", paths)

    def test_no_chunk_spans_two_topics(self) -> None:
        chunks = split_markdown(_SAMPLE_MD)
        for chunk in chunks:
            # 每个切片只属于一个标题路径
            self.assertNotIn("3.3 易混点", chunk.text)

    def test_long_text_split_keeps_heading(self) -> None:
        body = "\n\n".join(f"第 {index} 段内容。" * 20 for index in range(20))
        chunks = split_markdown(f"# 大章节\n\n{body}", max_chars=300)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(chunk.heading_path, "大章节")
            self.assertLessEqual(chunk.char_count, 400)

    def test_unheaded_text_uses_placeholder(self) -> None:
        chunks = split_markdown("一段没有任何标题的内容。")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].heading_path, "（未分节）")

    def test_empty_text_yields_no_chunks(self) -> None:
        self.assertEqual(split_markdown("   \n  "), [])

    def test_checksum_is_stable_and_sensitive(self) -> None:
        self.assertEqual(content_checksum("abc"), content_checksum("abc"))
        self.assertNotEqual(content_checksum("abc"), content_checksum("abd"))

    def test_compute_impact_detects_change(self) -> None:
        old = [Chunk(0, "A", "旧内容"), Chunk(1, "B", "保留")]
        new = [Chunk(0, "A", "新内容"), Chunk(1, "C", "新增")]
        report = compute_impact(old, new)
        self.assertEqual(report.changed, ["A"])
        self.assertEqual(report.removed, ["B"])
        self.assertEqual(report.added, ["C"])

    def test_sanitize_chunk_ids(self) -> None:
        valid, dropped = sanitize_chunk_ids([1, 2, "x", 99], {1, 2})
        self.assertEqual(valid, [1, 2])
        self.assertEqual(dropped, [99])


class TestSourceService(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db_path = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "test.db")
        init_db()
        self.training = queries.create_training(topic="英语虚拟语气", status="confirmed")

    def tearDown(self) -> None:
        if self._old_db_path is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db_path
        self._tmp.cleanup()

    def _import(self, source_type: str, content: str | None, title: str = "样例") -> svc.Source:
        source = svc.create_source(
            self.training.id, type=source_type, title=title, origin="unit-test", content=content
        )
        return svc.parse_source(source.id)

    def test_three_static_source_types(self) -> None:
        for source_type in svc.STATIC_SOURCE_TYPES:
            with self.subTest(source_type=source_type):
                source = self._import(source_type, "内容" if source_type != "ai_generated" else None)
                self.assertEqual(source.type, source_type)
                self.assertEqual(source.parse_status, "ok")
                self.assertEqual(source.org_id, svc.DEFAULT_ORG_ID)
                self.assertEqual(source.scope, "personal")
        self.assertEqual(len(svc.list_sources(self.training.id)), 3)

    def test_parse_creates_chunks_and_paths(self) -> None:
        source = self._import("user_paste", _SAMPLE_MD)
        chunks = svc.list_chunks(source.id)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(all(chunk.heading_path for chunk in chunks))
        self.assertEqual([chunk.ordinal for chunk in chunks], sorted(c.ordinal for c in chunks))

    def test_parse_is_idempotent(self) -> None:
        source = self._import("user_paste", _SAMPLE_MD)
        first = svc.list_chunks(source.id)
        again = svc.parse_source(source.id)
        second = svc.list_chunks(source.id)
        self.assertEqual(again.checksum, source.checksum)
        self.assertEqual(len(first), len(second))

    def test_damaged_source_can_be_marked_failed(self) -> None:
        source = self._import("user_upload", None, title="损坏的文件")
        failed = svc.mark_failed(source.id, "cannot parse: damaged file")
        self.assertIsNotNone(failed)
        self.assertEqual(failed.parse_status, "failed")
        self.assertIn("damaged", failed.parse_error or "")

    def test_search_hits_chunk_without_llm(self) -> None:
        self._import("user_paste", _SAMPLE_MD)

        from src.llm import client as client_module

        original = client_module.complete

        def _boom(*args: object, **kwargs: object) -> None:
            raise AssertionError("search must not call the LLM")

        client_module.complete = _boom  # type: ignore[assignment]
        try:
            hits = svc.search_chunks(self.training.id, "虚拟语气")
            self.assertTrue(hits)
            self.assertTrue(any("虚拟语气" in hit.text or "虚拟语气" in (hit.heading_path or "") for hit in hits))
        finally:
            client_module.complete = original  # type: ignore[assignment]

    def test_search_requires_training_scope(self) -> None:
        self._import("user_paste", _SAMPLE_MD)
        other = queries.create_training(topic="另一个训练", status="confirmed")
        self.assertEqual(svc.search_chunks(other.id, "虚拟语气"), [])

    def test_search_empty_query(self) -> None:
        self._import("user_paste", _SAMPLE_MD)
        self.assertEqual(svc.search_chunks(self.training.id, "   "), [])

    def test_chunk_link_drops_unknown_ids(self) -> None:
        source = self._import("user_paste", _SAMPLE_MD)
        real_ids = sorted(svc.existing_chunk_ids(source.id))
        valid, dropped = svc.link_chunk_ids([real_ids[0], 99999], source.id)
        self.assertEqual(valid, [real_ids[0]])
        self.assertEqual(dropped, [99999])

    def test_compute_impact_after_change(self) -> None:
        source = self._import("user_paste", _SAMPLE_MD)
        # 内容未变 → 空清单
        self.assertTrue(svc.compute_impact(source.id).is_empty)
        # 传入新内容 → 给出差异
        changed = _SAMPLE_MD + "\n\n## 3.4 新增章节\n\n新增的内容。\n"
        report = svc.compute_impact(source.id, changed)
        self.assertFalse(report.is_empty)
        self.assertIn("第三章 虚拟语气 > 3.4 新增章节", report.added)

    def test_unsupported_file_marks_unsupported(self) -> None:
        source = svc.create_source_from_file(
            self.training.id, filename="图片.png", data=b"\x89PNG"
        )
        self.assertEqual(source.parse_status, "unsupported")
        self.assertIn("png", (source.parse_error or "").lower())

    def test_broken_xlsx_marks_failed(self) -> None:
        source = svc.create_source_from_file(
            self.training.id, filename="乱表.xlsx", data=b"not a real xlsx"
        )
        self.assertEqual(source.parse_status, "failed")

    def test_xlsx_file_becomes_chunks(self) -> None:
        import io

        import openpyxl

        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = "题库"
        sheet.append(["题干", "选项", "正确答案", "解析"])
        sheet.append(["虚拟语气表示什么？", "A 事实 B 假设", "B", "表达与事实相反"])
        buffer = io.BytesIO()
        workbook.save(buffer)

        source = svc.create_source_from_file(
            self.training.id, filename="题库.xlsx", data=buffer.getvalue()
        )
        self.assertEqual(source.parse_status, "ok")
        chunks = svc.list_chunks(source.id)
        self.assertTrue(chunks)
        self.assertTrue(any("题目 1" in (chunk.heading_path or "") for chunk in chunks))

    def test_get_chunks_by_ids_returns_provenance(self) -> None:
        source = self._import("user_paste", _SAMPLE_MD)
        ids = sorted(svc.existing_chunk_ids(source.id))[:2]
        rows = svc.get_chunks_by_ids(ids)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["source_title"], "样例")
        self.assertTrue(rows[0]["heading_path"])
        self.assertEqual(svc.get_chunks_by_ids([]), [])


if __name__ == "__main__":
    unittest.main()
