# 2026-07-25 · fix · Streamlit 启动 ModuleNotFoundError + 清理 src/ 顶层旧 demo

## 变更摘要

`uv run streamlit run src/main.py` 启动时报 `ModuleNotFoundError: No module named 'src'`。
排查后发现两个独立问题，统一在此记录：

### Bug 1：Streamlit 子进程不继承 `uv run` 注入的 PYTHONPATH
- **现象**：`src/main.py` 第 23 行 `from src.db.sqlite import init_db` 抛 ModuleNotFoundError
- **根因**：Streamlit 把 `src/` 加进 `sys.path[0]`（脚本所在目录），但 `from src.X` 需要 `src/` 作为顶层 package。当 `src/` 已经在 sys.path[0] 时，Python 找的是 `src/src/X`（错的层级）
- **影响**：任何用 `uv run streamlit run src/main.py` 启动都会失败（无法 onboarding 任何用户）
- **修复**：`src/main.py` 顶部显式 `sys.path.insert(0, str(_PROJECT_ROOT))`，幂等

### Chore：清理 `src/` 顶层 6 个旧 demo 文件
- **现象**：`src/config.py`、`src/diagnoser.py`、`src/generator.py`、`src/logger.py`、`src/models.py`、`src/storage.py` 6 个顶层旧文件（项目初始试探期的 demo，Jul 22-23 创建），与新 MVP 完全无引用关系
- **影响**：
  - 命名冲突风险（`src/models.py` 与 `src/db/models.py` 同名）
  - 干扰新人 onboarding（新代码在 `src/llm/ src/db/ src/services/` 等子目录，旧代码在顶层）
  - 仓库体积 +3.7 KB 死代码
- **修复**：删除 6 文件。`grep` 全仓库确认无新代码引用
- **保留**：`src/__init__.py`（标记 src 为 package）、`src/main.py`（新入口）

## 影响范围

```
src/main.py             # +sys.path 注入
src/config.py           # -删除
src/diagnoser.py        # -删除
src/generator.py        # -删除
src/logger.py           # -删除
src/models.py           # -删除
src/storage.py          # -删除
src/__init__.py         # 保留（package 标识）
src/llm/... src/db/...  # 全部保留（无影响）
src/core/... src/services/... src/ui/... src/templates/...  # 全部保留
src/codemap.md          # 保留（旧架构档案，不修改；doc 标注"仅作参考 demo"）
```

## 相关文件路径

```
src/main.py:13-26   # sys.path 注入 + init_db
src/__init__.py     # 空 package 标识，保留
```

## 关联的 OpenSpec change id

无（chore 类变更不产生新 spec；fix 是 trainer-mvp-v1 实施产物的内务修正）

## 验证

```
uv run streamlit run src/main.py --server.headless true --server.port 8513
  → Uvicorn server started on :::8513 ✅（无 traceback）

DB_PATH=./data/test_e2e.db uv run python scripts/e2e_full_flow.py
  → e2e summary: 11/11 passed ✅

uv run python -m pytest tests/test_units.py -v
  → 30 passed, 13 subtests passed ✅
```

## Git

本次拆两个 commit：

```
(待提交) fix: src/main.py 显式注入 sys.path 让 Streamlit 子进程找到 src 包
(待提交) chore: 删除 src/ 顶层 6 个旧 demo 文件（无新代码引用）
```

## 不删的事（明确说明）

- **codemap.md**：旧架构文档，按 AGENTS.md 第 4 条约定"仅作参考 demo"保留作历史档案，不同步改
- **`.venv/`**、`.opencode/`、`.codegraph/`：AGENTS.md 明确不动
- **`data/trainer.db`**：用户真实数据，不删
- **`workspace/`**：包含 OpenSpec store + 旧试探文件，按 AGENTS.md "store 已注册 id=store" 不动 store 部分；record/ 子目录继续作为变更日志

## 启发

1. **Streamlit 子进程继承环境** — `uv run X` 在 venv 模式下注入的 PYTHONPATH 不会自动透传给 X 启动的 Python 子进程。任何带子进程的工具（Streamlit / jupyter / pytest-with-plugins / daemon tools）都需要在脚本顶部显式 sys.path 防御。这条经验值得记入项目"开发约定"
2. **死代码清理 = onboarding 友好的关键** — 6 个旧文件互相 import 形成闭环、但和真实架构完全脱节，这种"死循环"对新人理解代码库是负担。后续 Phase 2 通用化时建议在 README 加一句"项目自 v1.0 起重构，旧 demo 全部移除"

## 后续动作

- Phase 2（通用化）候选清单新增一项：`pyproject.toml` 把 `src/` 注册为 proper package，从根上消除 sys.path hack 的需求
- Phase 2 README 加一段"项目约定 / 开发守则"，把上面启发 1 的经验固化下来