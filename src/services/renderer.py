"""Render the 10 canonical training markdown files from a context dict."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Mapping

from jinja2 import ChainableUndefined, Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_FILENAMES: tuple[str, ...] = (
    "00_对象档案",
    "01_基线诊断",
    "02_训练目标",
    "03_资料库",
    "04_复习日历",
    "05_主动回忆题",
    "06_环境配置",
    "07_奖励机制",
    "08_每日反省",
    "09_边界与止",
)

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    undefined=ChainableUndefined,
    autoescape=False,
    keep_trailing_newline=True,
    trim_blocks=False,
    lstrip_blocks=False,
)

_templates: dict[str, Any] = {
    name: _env.get_template(f"{name}.md.j2") for name in _FILENAMES
}


def render_training_files(context: Mapping[str, Any]) -> dict[str, str]:
    """Render the 10 standard training markdown files from a context dict.

    The returned dict maps output filename (e.g. ``"00_对象档案.md"``) to its
    rendered markdown string. Missing or ``None`` context values are rendered
    as empty strings via the templates' ``default`` filters; nested list/dict
    access uses ``ChainableUndefined`` so undefined keys never raise.
    """
    payload: dict[str, Any] = dict(context)
    rendered: dict[str, str] = {}
    for name in _FILENAMES:
        try:
            rendered[f"{name}.md"] = _templates[name].render(**payload)
        except Exception:
            logger.exception("Failed to render template %s", name)
            raise
    return rendered


__all__ = ["render_training_files"]