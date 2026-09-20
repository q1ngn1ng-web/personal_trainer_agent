"""网络来源：抓取、正文抽取、快照。

对应 OpenSpec change ``training-source-selection`` 的阶段 B，决策见 ADR-0008。
边界（写死，不做例外）：只抓用户显式给出的 URL；不跟随页面内链接、不做站内爬取；
不做定时重抓；不绕过反爬与验证码；正文为空（单页应用）直接判失败，不产出空来源。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("src.services.web_source")

DEFAULT_TIMEOUT_S: float = 15.0

#: 用常见浏览器 UA，避免被最基础的 UA 过滤挡掉（这是基本礼貌，不是绕过反爬）
_BROWSER_UA: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

#: 抽取正文时直接跳过的标签
_SKIP_TAGS: frozenset[str] = frozenset(
    {"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "iframe", "svg"}
)

_HEADING_TAGS: dict[str, int] = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

_BLOCK_TAGS: frozenset[str] = frozenset(
    {"p", "div", "section", "article", "li", "tr", "br", "main", "blockquote", "pre", "td"}
)

_WS_RE = re.compile(r"[ \t\u00a0]+")
_BLANK_RE = re.compile(r"\n{3,}")


class WebSourceError(RuntimeError):
    """抓取或抽取失败。消息会直接展示给用户。"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FetchedPage:
    """一次抓取的结果。"""

    url: str
    final_url: str
    status: int
    html: str
    fetched_at: str


class _TextExtractor(HTMLParser):
    """极简正文抽取：跳过脚本/导航/页脚，保留标题层级与段落边界。

    不引入重量级依赖；需要更强抽取（如 trafilatura）时可替换本类而不动上层。
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        level = _HEADING_TAGS.get(name)
        if level:
            self._chunks.append(f"\n\n{'#' * level} ")
        elif name in _BLOCK_TAGS:
            self._chunks.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if name in _BLOCK_TAGS or name in _HEADING_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth or not data:
            return
        self._chunks.append(_WS_RE.sub(" ", data))

    def markdown(self) -> str:
        text = "".join(self._chunks)
        lines = [line.strip() for line in text.splitlines()]
        result = "\n".join(lines)
        return _BLANK_RE.sub("\n\n", result).strip()


def extract_main_text(html: str) -> str:
    """从 HTML 抽取正文并转成 Markdown 风格文本。"""
    parser = _TextExtractor()
    parser.feed(html or "")
    parser.close()
    return parser.markdown()


def fetch_url(url: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> FetchedPage:
    """抓取一个 URL。失败时抛 :class:`WebSourceError`，消息可直接展示。"""
    target = (url or "").strip()
    if not target:
        raise WebSourceError("网址不能为空")
    if not target.lower().startswith(("http://", "https://")):
        raise WebSourceError("网址必须以 http:// 或 https:// 开头")

    request = Request(
        target, headers={"User-Agent": _BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - 用户显式提供的 URL
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="ignore")
            return FetchedPage(
                url=target,
                final_url=response.geturl(),
                status=int(getattr(response, "status", 200) or 200),
                html=html,
                fetched_at=now_iso(),
            )
    except HTTPError as exc:
        if exc.code in (401, 403, 429):
            raise WebSourceError(f"目标站点拒绝访问（HTTP {exc.code}）") from exc
        raise WebSourceError(f"抓取失败（HTTP {exc.code}）") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise WebSourceError(f"无法访问该网址：{reason}") from exc
    except TimeoutError as exc:
        raise WebSourceError(f"抓取超时（>{timeout:.0f} 秒）") from exc
    except Exception as exc:  # 其它异常统一包装，保证失败信息可展示
        raise WebSourceError(f"抓取失败：{exc}") from exc


def fetch_and_extract(url: str, *, timeout: float = DEFAULT_TIMEOUT_S) -> tuple[FetchedPage, str]:
    """抓取并抽取正文；正文为空时按 ADR-0008 判失败。"""
    page = fetch_url(url, timeout=timeout)
    text = extract_main_text(page.html)
    if len(text) < 50:
        raise WebSourceError("该页面需要浏览器渲染（抓不到正文），暂不支持")
    return page, text


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "FetchedPage",
    "WebSourceError",
    "extract_main_text",
    "fetch_and_extract",
    "fetch_url",
    "now_iso",
]
