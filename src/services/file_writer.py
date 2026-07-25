"""Filesystem helpers for persisting rendered training files."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger("src.services.file_writer")

_UNSAFE_CHARS = re.compile(r"[\\/:\*\?\"<>\|\s]+")
_DIR_PREFIX = "training_"
_MAX_SLUG_LEN = 60


def sanitize_dir_name(topic: str) -> str:
    """Convert a topic string into a filesystem-safe directory name.

    Produces ``training_<slug>/`` where ``<slug>`` keeps alphanumerics,
    underscores and Chinese characters; ``/ \\ : * ? " < > |`` and whitespace
    are replaced with ``_``; consecutive underscores are collapsed; leading
    and trailing underscores are stripped; the slug is capped at 60 chars.
    """
    raw = topic or ""
    slug = _UNSAFE_CHARS.sub("_", raw)
    slug = re.sub(r"_+", "_", slug).strip("_")
    slug = slug[:_MAX_SLUG_LEN].rstrip("_")
    return f"{_DIR_PREFIX}{slug}"


def write_training_directory(
    base_dir: str | Path,
    dir_name: str,
    files: dict[str, str],
) -> Path:
    """Atomically write all rendered files into ``base_dir/dir_name``.

    The directory is created with mode 0o755, each file is written to a
    sibling ``.tmp`` file (0o644) and then moved into place via ``os.replace``
    so the final write is atomic. If any step fails, leftover ``.tmp`` files
    are removed and the original exception is re-raised.
    """
    base = Path(base_dir).expanduser().resolve()
    target = base / dir_name
    tmp_paths: list[Path] = []
    target.mkdir(parents=True, exist_ok=False)
    try:
        target.chmod(0o755)
        for name, content in files.items():
            final = target / name
            tmp = final.with_suffix(final.suffix + ".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.chmod(0o644)
            tmp_paths.append(tmp)
            os.replace(tmp, final)
    except Exception:
        for tmp in tmp_paths:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                logger.warning("Failed to clean up tmp file %s", tmp)
        raise
    return target.resolve()


def check_writable(path: Path) -> bool:
    """Return True if the parent directory of ``path`` is writable.

    If ``path`` is itself an existing directory, that directory is checked.
    """
    probe = path if path.is_dir() else path.parent
    if not probe.exists() or not probe.is_dir():
        return False
    return os.access(probe, os.W_OK)


__all__ = ["sanitize_dir_name", "write_training_directory", "check_writable"]