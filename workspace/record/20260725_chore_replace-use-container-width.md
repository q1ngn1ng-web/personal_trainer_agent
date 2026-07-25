# 2026-07-25 · chore · 替换 Streamlit 弃用参数 use_container_width → width='stretch'

## 变更摘要

Streamlit 控制台抛弃用警告：

> `use_container_width` will be removed after 2025-12-31.
> For `use_container_width=True`, use `width='stretch'`.
> For `use_container_width=False`, use `width='content'`.

### 替换规则

| 旧 | 新 |
|---|---|
| `use_container_width=True` | `width='stretch'` |
| `use_container_width=False` | `width='content'` |

本仓库仅出现 `True` 用法，无 `False` 用法。

### 受影响文件（4 个，共 19 处替换）

| 文件 | 替换处数 | 上下文 |
|---|---|---|
| `src/ui/page_home.py` | 4 | `st.dataframe` 调用（dataframe / metric 容器） |
| `src/ui/page_new_training.py` | 8 | `st.button` 调用（向导 4 步 + 完成页） |
| `src/ui/page_training.py` | 4 | `st.button` 调用（返回/链接/编辑） |
| `src/ui/page_review.py` | 2 | `st.dataframe` 调用（schedule / materials 校准表） |

## 影响范围

```
src/ui/page_home.py
src/ui/page_new_training.py
src/ui/page_training.py
src/ui/page_review.py
```

## 相关文件路径

见上表。均为 `src/ui/` 下页面模块，未触及业务逻辑（`src/services/`、`src/llm/`、`src/db/`、`src/core/`）。

## 关联的 OpenSpec change id

无（chore 类机械替换，不改变行为或 spec）

## 验证

```
grep "use_container_width" src/  → 0 hits ✅

uv run streamlit run src/main.py --server.headless true --server.port 8515
  → Uvicorn server started on :::8515（无 traceback，无 DeprecationWarning） ✅

uv run python -m pytest tests/test_units.py
  → 30 passed in 0.31s ✅
```

启动日志中已无 `use_container_width` 相关警告。

## 替换操作备注

`use_container_width=True` 在仓库内有两种上下文：
1. 形参列表中后接其他参数 → 末尾是逗号（4 处）
2. 形参列表末尾 → 末尾是 `)` 或 `):`（15 处）

第一次 `replaceAll` 只匹配了带逗号的 4 处，第二次才把剩下 15 处干掉。两轮替换是预期分批，非遗漏。

## 后续建议

- Phase 2 通用化前再 grep 一次 `use_container_width`，确认未引入新用法
- 此 deprecation 截止 2025-12-31（已过），下次 Streamlit 升级可能会硬切错误，所以这次替换即使不是"用户可见 bug"也值得做

## Git

```
(待提交) chore(ui): 替换 Streamlit 弃用参数 use_container_width → width='stretch'
```