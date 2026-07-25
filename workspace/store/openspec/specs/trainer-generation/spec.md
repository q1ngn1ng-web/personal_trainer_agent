# trainer-generation Specification

## Purpose
TBD - created by archiving change trainer-mvp-v1. Update Purpose after archive.
## Requirements
### Requirement: 用户能创建新训练主题
系统 SHALL 提供「新建训练」入口（Streamlit 页面或按钮），用户输入训练主题后能跑通完整创建流程。

#### Scenario: 主题输入页可达
- **WHEN** 用户在首页点击「新建训练」
- **THEN** 系统跳转到新建训练向导页

#### Scenario: 主题持久化入口
- **WHEN** 用户在向导中确认主题
- **THEN** 系统在 `trainings` 表写入一条记录（topic 字符串、status=created、created_at 时间戳），且该主题在首页训练列表中可见

### Requirement: 主题必须通过具体性校验
系统 SHALL 使用 LLM 评估主题是否「具体到可验证」，不通过的主题 MUST 被拒绝并给出可操作建议。

#### Scenario: 具体性通过
- **WHEN** 用户输入主题「3 周内背完 GRE 核心 1500 词」
- **THEN** LLM 判定通过，进入下一步

#### Scenario: 具体性不通过
- **WHEN** 用户输入主题「学 Python」
- **THEN** 系统显示「请具体到可验证的目标，例如：用 Python 写自动化脚本」，并提供 3-5 条具体化示例
- **THEN** 系统不进入下一步，要求用户重新输入

### Requirement: 系统自动生成关键词白名单
系统 SHALL 在主题确认后，使用 LLM 生成关键词白名单（10-15 个），并明确「必须覆盖数」（默认 2）与「禁止词」（默认空）。

#### Scenario: 关键词生成成功
- **WHEN** 主题确认
- **THEN** 系统调用 LLM 生成关键词清单（含 must_cover_count、forbidden 字段），并入库到 `trainings.keywords` 字段

#### Scenario: 关键词生成失败重试
- **WHEN** LLM 返回无法解析为 JSON
- **THEN** 系统最多重试 3 次（指数退避），最终失败时显示降级提示且不阻塞后续流程（关键词为空集走 fallback 路径）

### Requirement: 系统按十要素模板生成 10 份训练文件
系统 SHALL 按十要素（对象→基→的→器→序→术→境→奖→省→止）生成 10 份 md，文件名按 `00_对象档案.md` 到 `09_边界与止.md` 排序，并落盘到 `training_<主题>/` 目录。

#### Scenario: 文件成功落盘
- **WHEN** 10 份 md 生成完成
- **THEN** 系统在 `training_<主题>/` 下创建 10 个文件，每个文件大小 > 1KB
- **THEN** `trainings.directory` 字段写入目录绝对路径

#### Scenario: 目录命名清洗
- **WHEN** 主题为「Python asyncio/aiohttp 概念与实战」
- **THEN** 目录名为 `training_python_asyncio_aiohttp_概念与实战`（去除不安全字符）或等价安全命名

#### Scenario: 模板渲染失败
- **WHEN** Jinja2 模板渲染某份 md 抛异常
- **THEN** 系统记录错误到日志，标记该训练为 `status=failed`，并提示用户重试

### Requirement: 创建完成后跳转到日常 surface
系统 SHALL 在 10 份 md 落盘成功后，自动跳转到该训练的「今日任务」页面。

#### Scenario: 自动跳转
- **WHEN** 10 份 md 落盘成功
- **THEN** 系统自动跳转到该训练的「今日任务」页面（`page_daily.py`）

#### Scenario: 跳转失败兜底
- **WHEN** 跳转因异常失败（如页面不存在）
- **THEN** 系统显示「训练创建成功，点击这里进入今日任务」的可点击链接，链接到 `page_daily.py`

