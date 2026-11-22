"""用户偏好（change ``coach-memory-three-layers`` 任务 0.1 / D4）。

**边界硬约束**：偏好只影响呈现与节奏（提示开关 / 每日时长目标 / 题型倾向），
绝不影响学习内容与判分（合意困难——内容与标准不由舒适度决定）。
存储沿用 app_settings 键值先例（snake_case、布尔 "1"/"0" 模式，见 memory_service）。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from src.db.sqlite import get_connection

#: 提示开关键名（coach_hint），默认开启
COACH_HINT_ENABLED_KEY: str = "coach_hint_enabled"
#: 每日时长目标（分钟），喂将来的错峰调度，默认 30
DAILY_MINUTES_TARGET_KEY: str = "daily_minutes_target"
#: 题型倾向（出题形式）：any/choice/fill/qa，默认 any
QUESTION_TYPE_PREFERENCE_KEY: str = "question_type_preference"

#: 题型倾向的合法取值
QUESTION_TYPE_VALUES: tuple[str, ...] = ("any", "choice", "fill", "qa")

_BOOL_TRUE = ("1", "true", "yes", "on")
_BOOL_FALSE = ("0", "false", "no", "off")

#: 每日时长目标的合理区间（分钟）
MIN_DAILY_MINUTES: int = 5
MAX_DAILY_MINUTES: int = 480


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(conn: sqlite3.Connection | None = None) -> sqlite3.Connection:
    return conn if conn is not None else get_connection()


def preference_defaults() -> dict[str, str]:
    """偏好键白名单与默认值（键白名单校验的唯一出处）。"""
    return {
        COACH_HINT_ENABLED_KEY: "1",
        DAILY_MINUTES_TARGET_KEY: "30",
        QUESTION_TYPE_PREFERENCE_KEY: "any",
    }


def validate_preference(key: str, value: Any) -> str:
    """校验并归一化单个偏好值；非法键 / 非法值抛 ValueError（端点层转 400）。"""
    if key not in preference_defaults():
        raise ValueError(f"未知偏好键：{key}")
    normalized = str(value).strip()
    if key == COACH_HINT_ENABLED_KEY:
        low = normalized.lower()
        if low in _BOOL_TRUE:
            return "1"
        if low in _BOOL_FALSE:
            return "0"
        raise ValueError(f"{key} 只接受布尔语义的取值（1/true/yes/on 或 0/false/no/off）")
    if key == DAILY_MINUTES_TARGET_KEY:
        try:
            minutes = int(normalized)
        except ValueError as exc:
            raise ValueError(f"{key} 必须是整数分钟") from exc
        if not (MIN_DAILY_MINUTES <= minutes <= MAX_DAILY_MINUTES):
            raise ValueError(
                f"{key} 取值范围 {MIN_DAILY_MINUTES}-{MAX_DAILY_MINUTES} 分钟"
            )
        return str(minutes)
    # 题型倾向
    if normalized not in QUESTION_TYPE_VALUES:
        raise ValueError(
            f"{key} 取值必须是 {'/'.join(QUESTION_TYPE_VALUES)} 之一"
        )
    return normalized


def get_preferences(*, conn: sqlite3.Connection | None = None) -> dict[str, str]:
    """读全部偏好（未设置的键回落默认值）。"""
    active = _connect(conn)
    own = conn is None
    try:
        keys = tuple(preference_defaults().keys())
        placeholders = ", ".join("?" for _ in keys)
        rows = active.execute(
            f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})", keys
        ).fetchall()
    finally:
        if own:
            active.close()
    stored = {str(row["key"]): str(row["value"]) for row in rows}
    return {**preference_defaults(), **stored}


def is_coach_hint_enabled(*, conn: sqlite3.Connection | None = None) -> bool:
    """连败提示开关，默认开启；显式写 0/false/no/off 才关闭。"""
    return get_preferences(conn=conn)[COACH_HINT_ENABLED_KEY] == "1"


def set_preferences(
    values: dict[str, Any], *, conn: sqlite3.Connection | None = None
) -> dict[str, str]:
    """批量写入：先全部校验再落库（非法即整批拒绝），返回归一化后的全量偏好。"""
    normalized: dict[str, str] = {}
    for key, value in values.items():
        normalized[key] = validate_preference(key, value)
    active = _connect(conn)
    own = conn is None
    try:
        for key, value in normalized.items():
            active.execute(
                "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = excluded.updated_at",
                (key, value, _now()),
            )
        if own:
            active.commit()
    finally:
        if own:
            active.close()
    return get_preferences(conn=active if not own else None)


__all__ = [
    "COACH_HINT_ENABLED_KEY",
    "DAILY_MINUTES_TARGET_KEY",
    "QUESTION_TYPE_PREFERENCE_KEY",
    "QUESTION_TYPE_VALUES",
    "get_preferences",
    "is_coach_hint_enabled",
    "preference_defaults",
    "set_preferences",
    "validate_preference",
]
