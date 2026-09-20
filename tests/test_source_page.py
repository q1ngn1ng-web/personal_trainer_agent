"""资料来源页的 UI 回归测试（Streamlit AppTest）。

锁住两条容易退化的验收点：未确认目的的训练不提供导入入口；页面不出现网络来源入口（阶段 B 才做）。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_WRAPPER = """import sys
sys.path.insert(0, {root!r})
from src.ui.page_sources import render
render()
"""


class TestSourcePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._old_db_path = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(cls._tmpdir.name) / "page.db")
        wrapper = Path(cls._tmpdir.name) / "page_sources_app.py"
        wrapper.write_text(_WRAPPER.format(root=str(ROOT)), encoding="utf-8")
        cls._wrapper = str(wrapper)
        from src.db.sqlite import init_db

        init_db()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._old_db_path is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = cls._old_db_path
        cls._tmpdir.cleanup()

    def _app(self, training_id: int | None = None):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(self._wrapper, default_timeout=60)
        app.run()
        if training_id is not None:
            app.query_params["training_id"] = str(training_id)
            app.run()
        return app

    def test_no_training_shows_hint(self) -> None:
        from src.db import queries

        if queries.list_trainings():
            self.skipTest("库里已有训练，跳过空态用例")
        app = self._app()
        self.assertTrue(any("还没有任何训练" in info.value for info in app.info))

    def test_draft_training_blocks_import(self) -> None:
        from src.db import queries

        training = queries.create_training(topic="草稿训练", status="draft")
        app = self._app(training.id)
        self.assertTrue(any("确认训练目标" in warning.value for warning in app.warning))
        self.assertEqual(len(app.tabs), 0)

    def test_confirmed_training_offers_three_static_sources_only(self) -> None:
        from src.db import queries

        training = queries.create_training(topic="英语虚拟语气", status="confirmed")
        app = self._app(training.id)
        labels = [tab.label for tab in app.tabs]
        self.assertEqual(len(labels), 3)
        self.assertTrue(any("粘贴文本" in label for label in labels))
        self.assertTrue(any("上传文件" in label for label in labels))
        self.assertTrue(any("AI 生成" in label for label in labels))
        joined = " ".join(labels)
        self.assertNotIn("网络", joined)
        self.assertNotIn("网址", joined)

    def test_paste_source_is_parsed_into_chunks(self) -> None:
        from src.db import queries
        from src.services import source_service as svc

        training = queries.create_training(topic="切片测试", status="confirmed")
        app = self._app(training.id)
        app.text_input(key="src_paste_title").set_value("讲义")
        app.text_area(key="src_paste_body").set_value(
            "# 第一章\n\n## 1.1 小节\n\n第一节的内容。\n\n## 1.2 小节\n\n第二节的内容。"
        )
        app.button(key="src_paste_submit").click()
        app.run()

        self.assertFalse(app.exception)
        sources = svc.list_sources(training.id)
        self.assertEqual(len(sources), 1)
        chunks = svc.list_chunks(sources[0].id)
        self.assertEqual(
            [chunk.heading_path for chunk in chunks],
            ["第一章 > 1.1 小节", "第一章 > 1.2 小节"],
        )


if __name__ == "__main__":
    unittest.main()
