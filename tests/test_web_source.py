"""网络来源测试：正文抽取、失败处理、快照落库。"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.db import queries  # noqa: E402
from src.db.sqlite import init_db  # noqa: E402
from src.services import source_service as svc  # noqa: E402
from src.services import web_source  # noqa: E402

_HTML = """<html><head><title>虚拟语气</title><style>.a{color:red}</style></head>
<body>
<nav>首页 产品 关于</nav>
<h1>第三章 虚拟语气</h1>
<p>虚拟语气用于表达与事实相反的假设。</p>
<h2>3.2 用法</h2>
<p>主句用 would + 动词原形。</p>
<script>console.log('tracking')</script>
<footer>版权所有</footer>
</body></html>"""


class TestExtraction(unittest.TestCase):
    def test_strips_nav_script_footer(self) -> None:
        text = web_source.extract_main_text(_HTML)
        self.assertIn("虚拟语气", text)
        for noise in ("首页 产品", "console.log", "版权所有", "color:red"):
            self.assertNotIn(noise, text)

    def test_keeps_heading_levels(self) -> None:
        text = web_source.extract_main_text(_HTML)
        self.assertIn("# 第三章 虚拟语气", text)
        self.assertIn("## 3.2 用法", text)

    def test_empty_html(self) -> None:
        self.assertEqual(web_source.extract_main_text(""), "")


class TestFetchErrors(unittest.TestCase):
    def test_requires_scheme(self) -> None:
        with self.assertRaises(web_source.WebSourceError) as ctx:
            web_source.fetch_url("example.com")
        self.assertIn("http", str(ctx.exception).lower())

    def test_empty_url(self) -> None:
        with self.assertRaises(web_source.WebSourceError):
            web_source.fetch_url("   ")

    def test_empty_body_is_treated_as_spa(self) -> None:
        original = web_source.fetch_url
        web_source.fetch_url = lambda url, timeout=15.0: web_source.FetchedPage(  # type: ignore[assignment]
            url=url, final_url=url, status=200, html="<div id=app></div>", fetched_at="t"
        )
        try:
            with self.assertRaises(web_source.WebSourceError) as ctx:
                web_source.fetch_and_extract("https://example.com")
            self.assertIn("浏览器渲染", str(ctx.exception))
        finally:
            web_source.fetch_url = original  # type: ignore[assignment]


class TestWebSourceService(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = str(Path(self._tmp.name) / "web.db")
        init_db()
        self.training = queries.create_training(topic="网络来源测试", status="confirmed")

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = self._old_db
        self._tmp.cleanup()

    def _patch_fetch(self, text: str | None, error: Exception | None = None):
        def _fake(url: str, timeout: float = 15.0):
            if error is not None:
                raise error
            page = web_source.FetchedPage(
                url=url, final_url=url, status=200, html="<html></html>", fetched_at="2026-09-20T00:00:00Z"
            )
            return page, text

        self._orig = web_source.fetch_and_extract
        web_source.fetch_and_extract = _fake  # type: ignore[assignment]

    def tearDown_patch(self) -> None:
        if hasattr(self, "_orig"):
            web_source.fetch_and_extract = self._orig  # type: ignore[assignment]

    def test_successful_fetch_stores_snapshot(self) -> None:
        self._patch_fetch("# 标题\n\n" + "正文内容。" * 20)
        try:
            source = svc.fetch_web_source(self.training.id, "https://example.com/doc")
        finally:
            self.tearDown_patch()
        self.assertEqual(source.type, "web_url")
        self.assertEqual(source.parse_status, "ok")
        self.assertEqual(source.origin_url, "https://example.com/doc")
        self.assertTrue(source.fetched_at)
        self.assertTrue(svc.list_chunks(source.id))

    def test_failed_fetch_keeps_record_with_reason(self) -> None:
        self._patch_fetch(None, web_source.WebSourceError("目标站点拒绝访问（HTTP 403）"))
        try:
            source = svc.fetch_web_source(self.training.id, "https://example.com/blocked")
        finally:
            self.tearDown_patch()
        self.assertEqual(source.parse_status, "failed")
        self.assertIn("403", source.parse_error or "")
        # 失败也要在列表里看得到
        self.assertEqual(len(svc.list_sources(self.training.id)), 1)

    def test_disabled_source_excluded_from_search(self) -> None:
        source = svc.create_source(
            self.training.id, type="user_paste", title="讲义", content="# 章\n\n虚拟语气的内容。"
        )
        svc.parse_source(source.id)
        self.assertTrue(svc.search_chunks(self.training.id, "虚拟语气"))
        svc.set_source_enabled(source.id, False)
        self.assertEqual(svc.search_chunks(self.training.id, "虚拟语气"), [])
        svc.set_source_enabled(source.id, True)
        self.assertTrue(svc.search_chunks(self.training.id, "虚拟语气"))

    def test_refresh_requires_web_source(self) -> None:
        source = svc.create_source(self.training.id, type="user_paste", title="文本", content="x")
        with self.assertRaises(ValueError):
            svc.refresh_snapshot(source.id)


if __name__ == "__main__":
    unittest.main()
