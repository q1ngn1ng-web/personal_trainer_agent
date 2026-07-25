# `src/cli/` 代码地图

## 分析范围

本说明仅基于 `src/cli/*.py`：当前目录中可分析的 Python 文件为 `__main__.py`。`codemap.md` 是本目录的说明文件，不作为运行模块。

## 命令入口

- 模块入口：`src/cli/__main__.py`
- Python 模块执行入口：文件末尾的
  `if __name__ == "__main__": main()`。
- CLI 主函数：`main()`，创建 `argparse.ArgumentParser`，并将程序名设置为 `trainer`。
- 从本目录代码可确认的命令入口形式是模块执行，例如：
  `uv run python -m src.cli`
- `prog="trainer"` 只影响 argparse 的用法/帮助文本显示；本文件没有定义独立的安装脚本或可执行文件注册逻辑，因此不能仅凭本目录代码断定 `trainer` 命令已被系统安装。

## 命令与参数

当前只注册一个必需的子命令：

```text
trainer init-db
```

- `init-db`
  - 作用：创建包含全部表的 SQLite 数据库。
  - 帮助文本：`Create SQLite database with all tables`。
  - 不接受本文件定义的额外位置参数或选项。
- 子命令本身是必需的：未提供命令时，argparse 会报错并退出，而不会进入数据库初始化逻辑。
- 未知命令或不符合 argparse 定义的参数会由 argparse 负责报错并退出。

## 控制流

1. 以 `python -m src.cli` 执行时，进入 `__main__.py` 的模块保护分支并调用 `main()`。
2. `main()` 创建解析器，并通过 `add_subparsers(dest="cmd", required=True)` 创建必需的子命令解析器。
3. 注册 `init-db` 子命令后调用 `parse_args()` 解析命令行参数。
4. 当 `args.cmd == "init-db"` 时调用导入的 `init_db()`。
5. `init_db()` 返回后打印 `✅ Database initialized`。
6. 本文件没有显式的异常捕获、事务处理、返回码处理或其他子命令分发逻辑；数据库初始化失败时，异常处理行为由 `init_db()` 或外层运行环境决定。

## 依赖模块

### 标准库

- `argparse`：定义 CLI 解析器、必需子命令和参数错误处理。
- `logging`：创建名为 `src.db.cli` 的 logger。
- `__future__.annotations`：启用延迟注解求值；当前文件中的 `main()` 没有实际类型注解依赖。

### 项目模块

- `src.db.sqlite.init_db`：`init-db` 命令唯一调用的项目依赖，负责 SQLite 数据库初始化。

文件中定义了：

```python
logger = logging.getLogger("src.db.cli")
```

但当前 CLI 控制流没有使用该 logger，也没有配置日志级别或日志处理器。

## 运行方式

推荐使用项目约定的 uv 环境执行模块入口：

```bash
uv run python -m src.cli init-db
```

也可以先查看 argparse 帮助：

```bash
uv run python -m src.cli --help
uv run python -m src.cli init-db --help
```

执行 `init-db` 时，CLI 仅负责参数解析、调用 `init_db()` 和成功提示；数据库路径、表结构及具体初始化行为不在 `src/cli/*.py` 中实现。

## 结构摘要

```text
src/cli/__main__.py
└── main()
    ├── 创建 ArgumentParser(prog="trainer")
    ├── 注册必需子命令 init-db
    ├── parse_args()
    ├── init_db()
    └── 打印初始化成功消息
```
