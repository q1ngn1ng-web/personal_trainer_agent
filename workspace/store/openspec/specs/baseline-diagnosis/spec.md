# baseline-diagnosis Specification

## Purpose
TBD - created by archiving change trainer-mvp-v1. Update Purpose after archive.
## Requirements
### Requirement: 系统为新训练生成 3 道基线诊断题
系统 SHALL 在训练创建流程中，使用 LLM 生成 3 道前提性诊断题，题型覆盖概念理解 / 读代码 / 写代码三种内容维度。

#### Scenario: 关键词约束的题目生成
- **WHEN** 关键词白名单已生成（如含 `event loop / coroutine / await / aiohttp`）
- **THEN** LLM 生成的每道题 MUST 覆盖至少 1-2 个关键词
- **THEN** LLM 输出受 JSON Schema 约束：每道题含 `dimension`（concept/read/write）、`difficulty`（1-3）、`question`、`reference_answer`

#### Scenario: 关键词覆盖率校验
- **WHEN** LLM 返回题目 JSON
- **THEN** 系统对每题做关键词覆盖率检查；任一题不达标则重试 LLM（最多 3 次）
- **THEN** 3 次仍不达标时，使用 fallback：人工指定的 2 道默认概念题 + 1 道万能应用题

#### Scenario: 禁止词约束生效
- **WHEN** 关键词白名单中含 `forbidden: ["tornado", "fastapi 实现细节"]`
- **THEN** LLM 生成题目 MUST 不涉及禁止词；命中禁止词则重试或降级

### Requirement: 系统对用户作答评分并判定基线档位
系统 SHALL 在用户提交 3 道题作答后，使用 LLM 对每题做评分（✅掌握 / ⚠️半掌握 / ❌缺失），并综合输出基线档位（高 / 中 / 低）。

#### Scenario: 评分逻辑
- **WHEN** 用户提交 3 道题作答
- **THEN** LLM 返回每题 `score`（mastered / partial / missing）与 `notes`
- **THEN** 综合基线档位计算规则：3/3 掌握 = 高；2/3 掌握且无缺失 = 中；任意缺失 = 低
- **THEN** 档位与每题 notes 写入 `baseline_history` 表（baseline_score 数字 + dimension JSON）

#### Scenario: 模糊点识别
- **WHEN** 用户在某题为 partial
- **THEN** 该知识点加入训练资料的「补强复习项」清单（写入 `trainings.review_items` JSON 字段）

### Requirement: 基线「低」时生成预训练清单
系统 SHALL 在综合基线档位判定为「低」时，使用 LLM 生成 5-10 个基础概念 + 推荐资料的预训练清单。

#### Scenario: 低基线生成预训练清单
- **WHEN** 综合基线档位 = 低
- **THEN** 系统使用 LLM 生成 5-10 个基础概念 + 推荐资料的预训练清单
- **THEN** 清单写入 `trainings.pretrain_checklist` JSON 字段，并在 `00_对象档案.md` 中追加一段「预训练建议」

#### Scenario: 中高基线不生成预训练清单
- **WHEN** 综合基线档位 = 中 或 高
- **THEN** 不生成预训练清单（`pretrain_checklist` 保持空）

### Requirement: 基线诊断完整结果写入训练文件
系统 SHALL 在评分完成后，把 3 道题、用户作答、评分、基线档位写入对应的训练文件。

#### Scenario: 基线结果落到 md
- **WHEN** 评分完成
- **THEN** 系统把 3 道题、用户作答、评分、基线档位渲染到 `01_基线诊断.md`
- **THEN** 同步更新 `00_对象档案.md` 的「当前基线」字段
- **THEN** 文件落盘后从训练目录可读

