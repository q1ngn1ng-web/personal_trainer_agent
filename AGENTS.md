# AGENTS.md

## 项目概况
个人训练师 Agent。Python + Streamlit 应用，LLM 集成（DeepSeek / MiniMax / DashScope Embedding），SQLite 存于 `data/trainer.db`。

## 目录约定
| 目录 | 用途 | 重要程度 |
|---|---|---|
| `src/` | 主程序入口（Streamlit demo） | ⚠️ 仅作参考 demo，不要花精力重构 |
| `data/trainer.db` | SQLite 数据库 | 不要手动改 |
| `docs/` | 训练理论参考文档（培训十要素、学习本质等） | 只读资料 |
| `workspace/` | 个人工作区 | 见下方规则 |
| `workspace/record/` | **变更日志目录**（必读） | 每次重大更新必写 |
| `workspace/store/` | OpenSpec store（已注册 id=`store`） | spec / change 都走这里 |
| `workspace/training_list的基本使用/` | 训练清单使用文档 | 只读 |
| `.opencode/` | OpenCode skills & commands | 不要移动 |

## 强制规则

### 1. 变更记录（每次重大更新必做）
每次完成一个有意义的变更，必须在 `workspace/record/` 下新增一个 Markdown 文件，**bug 修复和功能更新分开记录**：
- 文件命名：`YYYYMMDD_类型_简短描述.md`，类型用 `fix` / `feat` / `refactor` / `chore` / `docs`
- 每个文件记录：变更摘要、影响范围、相关文件路径、关联的 OpenSpec change id（若有）
- 一个变更一个文件，不要混写

### 2. Git 提交
- 每次重大更新后 `git add` + `git commit`
- commit message 简明扼要，说明"做了什么"和"为什么"
- 涉及多个独立变更时拆成多个 commit

### 3. Python 运行环境
- 所有 Python 脚本必须用 **uv** 运行，不要直接调 `python` / `pip`
- 用 `uv run <script>` 执行脚本，自动激活 `.venv`
- 用 `uv pip install <pkg>` 安装依赖，并在 `requirements.txt` 同步追加
- 不要改 `.venv/` 里任何东西（uv 管）

### 4. OpenSpec 工作流
本项目已注册 OpenSpec store（id = `store`）。涉及功能/规格变更时：
- 先 `/opsx:propose "<想法>"` 创建 proposal
- 走完 `apply → archive` 闭环
- 命令记得带 `--store store`（opencode 自动处理）

## 不要做的事
- 不要把 `.opencode/` 移出项目根
- 不要重构 `src/` 下的 demo 代码（用户明确说"不用过多关注"）
- 不要把 `data/trainer.db` 提交进 git
- 不要把 `.env` 提交进 git（包含 API key）

## 常用命令
```bash
# 启动 demo（走 uv）
uv run streamlit run src/main.py

# 运行任意 Python 脚本
uv run python <script.py>

# 安装新依赖（记得同步追加到 requirements.txt）
uv pip install <pkg>

# OpenSpec 操作（store 已注册）
openspec list --store store
openspec new change <id> --store store
openspec validate --store store
```

## Repository Map

> 仓库的总览地图与各子目录的代码地图。**新同学先看 `codemap.md` 再看 `docs/architecture.md`，再按需下钻子目录地图。**

- 总览：[codemap.md](codemap.md) — 仓库地图（Repository Atlas），目录职责表 + 端到端流程 + 新人阅读顺序
- 架构：[docs/architecture.md](docs/architecture.md) — 分层架构图 + 关键业务流程图 + 模块边界 + 数据存储 + 设计决策
- 子地图：
  - [src/codemap.md](src/codemap.md) — `src/` 根目录（入口 / 配置 / 早期路径模块）
  - [src/core/codemap.md](src/core/codemap.md) — 领域原语层（element / training / baseline / content_dim）
  - [src/db/codemap.md](src/db/codemap.md) — 持久化层（sqlite / queries / models / tables.sql）
  - [src/llm/codemap.md](src/llm/codemap.md) — LLM 适配层（client / prompts / schema / validators / retry / fallback）
  - [src/services/codemap.md](src/services/codemap.md) — 业务编排层（14 个 service）
  - [src/ui/codemap.md](src/ui/codemap.md) — Streamlit 视图层（5 个 page_*）
  - [src/cli/codemap.md](src/cli/codemap.md) — CLI 入口（`init-db`）