"""Prompt templates and version registry."""
from __future__ import annotations

TOPIC_VALIDATION_PROMPT: str = """你是一名严格的主题评审员。请评估用户提交的训练主题是否清晰、可训练。

主题: {topic}
描述: {description}

请按以下 JSON Schema 严格输出（不要任何额外文字、不要 markdown 围栏、不要前后缀）:
{schema}

要求:
1. is_valid: 主题是否清晰、可在 4-8 周内训练达成
2. suggestions: 让主题更聚焦、可衡量的具体修改建议（数组，可为空）
3. reason: 简要判定理由
"""

TOPIC_VALIDATION_PROMPT_VERSION: str = "v1.0.0"

KEYWORD_GENERATION_PROMPT: str = """你是关键词白名单设计助手。请基于主题与描述，提炼训练期间必须覆盖的核心关键词。

主题: {topic}
描述: {description}

请按以下 JSON Schema 严格输出（不要任何额外文字、不要 markdown 围栏、不要前后缀）:
{schema}

要求:
1. keywords: 训练期内必须掌握的关键词数组（建议 8-15 个）
2. must_cover_count: 每道诊断题至少应覆盖的关键词数量（建议 1-2）
3. forbidden: 训练范围内明确禁止使用的工具或话题（如已退役的框架、跑题内容）
"""

KEYWORD_GENERATION_PROMPT_VERSION: str = "v1.0.0"

BASELINE_Q_PROMPT: str = """你是基线诊断出题助手。请基于主题、描述与关键词白名单，生成 3 道前提性诊断题。

主题: {topic}
描述: {description}
关键词白名单: {keywords}
禁止词: {forbidden}

请按以下 JSON Schema 严格输出（不要任何额外文字、不要 markdown 围栏、不要前后缀）:
{schema}

要求:
1. 恰好 3 道题，questions 数组长度 = 3
2. dimension 取值: "concept"（概念理解）/ "read"（读代码）/ "write"（写代码）三类各 1 题
3. difficulty 取值: 1 / 2 / 3，可不完全一致
4. 每题 question 文本必须覆盖关键词白名单中至少 1 个关键词（大小写不敏感）
5. 每题禁止出现 forbidden 中的词
6. reference_answer 给出可评判的参考答案要点
"""

BASELINE_Q_PROMPT_VERSION: str = "v1.0.0"

BASELINE_SCORING_PROMPT: str = """你是基线诊断评分员。请根据用户对 3 道诊断题的作答，对每题给出掌握度评分，并综合判定基线档位。

主题: {topic}
题目与参考答案:
{questions}
用户作答:
{answers}

请按以下 JSON Schema 严格输出（不要任何额外文字、不要 markdown 围栏、不要前后缀）:
{schema}

要求:
1. scores 数组按 question_idx 顺序逐题给出
2. score 取值: "mastered"（掌握）/ "partial"（半掌握）/ "missing"（缺失）
3. notes 给出判定依据（答对哪些点、缺哪些点）
4. overall: 综合档位 "high"（3/3 掌握）/ "mid"（2/3 掌握且无缺失）/ "low"（任意缺失）
5. partial_topics: 列出所有半掌握题对应的知识点
"""

BASELINE_SCORING_PROMPT_VERSION: str = "v1.0.0"

WEEKLY_CALIBRATION_PROMPT: str = """你是周复盘校准裁决助手。请根据本周机械指标与基线，给出新一周的训练校准建议。

主题: {topic}
当前基线分数: {baseline_score}
用户目标: {goal}
本周机械指标(JSON): {metrics}

请按以下 JSON Schema 严格输出（不要任何额外文字、不要 markdown 围栏、不要前后缀）:
{schema}

要求:
1. baseline_score_delta: 本周基线调整量，范围 -1.0 ~ +1.0
2. schedule_adjustment: 字典，键为主题单元名，值为 "降低密度" / "升级" / "维持"
3. material_recommendations: 资料增减建议数组，每项含 action/ref/reason
4. reward_refresh: 本周奖励调整建议（中文短句）
5. next_week_focus: 下周重点内容维度（中文短句）
"""

WEEKLY_CALIBRATION_PROMPT_VERSION: str = "v1.0.0"

MD_GENERATION_PROMPT: str = """你是个人训练文件生成助手。请基于主题、关键词、基线档位，生成完整训练文件包（恰好 10 个 markdown 文件）。

主题: {topic}
描述: {description}
关键词白名单: {keywords}
当前基线档位: {baseline_overall}
训练单元清单: {units}

请按以下 JSON Schema 严格输出（不要任何额外文字、不要 markdown 围栏、不要前后缀）:
{schema}

要求:
1. files 数组恰好 10 项
2. 文件名遵循十要素命名: 00_对象档案.md / 01_基线诊断.md / 02_单元目标.md / 03_训练日历.md / 04_复习日历.md / 05_材料清单.md / 06_闯关任务.md / 07_回忆题库.md / 08_三省模板.md / 09_复盘快照.md
3. 每个 content 字段为该文件的完整 markdown 内容（不含围栏代码块）
4. 内容贴合主题，引用关键词，禁止出现与训练无关的虚构数据
"""

MD_GENERATION_PROMPT_VERSION: str = "v1.0.0"

PRETRAIN_CHECKLIST_PROMPT: str = """你是低基线预训练清单助手。请为基线档位为「低」的用户生成补强预训练清单。

主题: {topic}
关键词白名单: {keywords}
薄弱知识点: {weak_topics}

请按以下 JSON Schema 严格输出（不要任何额外文字、不要 markdown 围栏、不要前后缀）:
{schema}

要求:
1. items 数组 5-10 项
2. 每项 concept 是 1 个必须先掌握的基础概念
3. materials 是该概念对应的推荐学习资料列表（书 / 文档 / 教程 / 视频名）
4. 概念顺序按从最基础到最进阶排列
"""

PRETRAIN_CHECKLIST_PROMPT_VERSION: str = "v1.0.0"

PROMPT_REGISTRY: dict[str, tuple[str, str]] = {
    "topic_validation": (TOPIC_VALIDATION_PROMPT, TOPIC_VALIDATION_PROMPT_VERSION),
    "keyword_generation": (KEYWORD_GENERATION_PROMPT, KEYWORD_GENERATION_PROMPT_VERSION),
    "baseline_q": (BASELINE_Q_PROMPT, BASELINE_Q_PROMPT_VERSION),
    "baseline_scoring": (BASELINE_SCORING_PROMPT, BASELINE_SCORING_PROMPT_VERSION),
    "weekly_calibration": (WEEKLY_CALIBRATION_PROMPT, WEEKLY_CALIBRATION_PROMPT_VERSION),
    "md_generation": (MD_GENERATION_PROMPT, MD_GENERATION_PROMPT_VERSION),
    "pretrain_checklist": (PRETRAIN_CHECKLIST_PROMPT, PRETRAIN_CHECKLIST_PROMPT_VERSION),
}