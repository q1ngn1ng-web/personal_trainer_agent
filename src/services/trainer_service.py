"""Orchestrator for the new-training flow: validation → keywords → baseline → scoring → render → write."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.element import BaselineLevel, TrainingStatus
from src.core.training import Training as DomainTraining
from src.db.queries import (
    add_baseline_history,
    create_training as create_training_row,
    record_llm_call,
    update_training,
)
from src.llm.client import complete
from src.llm.prompts import PROMPT_REGISTRY
from src.llm.schema import SCHEMA_REGISTRY
from src.services.baseline_service import (
    BaselineQuestion,
    BaselineQuestions,
    generate_baseline_questions,
)
from src.services.file_writer import (
    check_writable,
    sanitize_dir_name,
    write_training_directory,
)
from src.services.keyword_service import KeywordResult, generate_keywords
from src.services.renderer import render_training_files
from src.services.scoring_service import ScoringResult, score_baseline
from src.services.topic_validation import TopicValidationResult, validate_topic

logger = logging.getLogger("src.services.trainer_service")


class TrainerCreationError(Exception):
    """Raised when the new-training orchestrator fails at a specific step."""

    def __init__(self, step: str, original: BaseException) -> None:
        super().__init__(f"create_training failed at step '{step}': {original}")
        self.step = step
        self.original = original


_BASELINE_SCORE_MAP: dict[str, float] = {"high": 5.0, "mid": 3.0, "low": 1.0}
_SCORE_DISPLAY: dict[str, str] = {
    "mastered": "✅掌握",
    "partial": "⚠️半掌握",
    "missing": "❌缺失",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _cleanup_dir(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.is_dir():
            for child in path.iterdir():
                try:
                    if child.is_file() or child.is_symlink():
                        child.unlink()
                    else:
                        import shutil
                        shutil.rmtree(child)
                except OSError:
                    logger.warning("trainer_service: failed to remove %s during cleanup", child)
            try:
                path.rmdir()
            except OSError:
                logger.warning("trainer_service: failed to remove dir %s", path)
    except OSError:
        logger.warning("trainer_service: cleanup of %s raised", path)


def _build_pretrain_variables(topic: str, keywords: list[str], weak_topics: list[str]) -> dict[str, Any]:
    return {
        "topic": topic,
        "keywords": keywords,
        "weak_topics": weak_topics,
    }


def _generate_pretrain_checklist(
    topic: str,
    keywords: list[str],
    weak_topics: list[str],
) -> list[dict[str, Any]]:
    variables = _build_pretrain_variables(topic, keywords, weak_topics)
    template, _ = PROMPT_REGISTRY["pretrain_checklist"]
    schema = SCHEMA_REGISTRY["pretrain_checklist"]
    variables_with_schema = {**variables, "schema": json.dumps(schema, ensure_ascii=False, indent=2)}
    input_text = template.format(**variables_with_schema)

    fallback_used = 0
    fallback_items: list[dict[str, Any]] = []
    try:
        result = complete(prompt_name="pretrain_checklist", variables=variables)
    except Exception as exc:
        logger.warning("trainer_service: pretrain_checklist LLM failed: %s", exc)
        try:
            record_llm_call(
                call_purpose="pretrain_checklist",
                prompt_name="pretrain_checklist",
                prompt_version=PROMPT_REGISTRY["pretrain_checklist"][1],
                model="unknown",
                input_text=input_text,
                latency_ms=0,
                tokens_in=0,
                tokens_out=0,
                output_text=None,
                output_json=None,
                retry_count=0,
                fallback_used=0,
                validation_result="fail",
                failure_reason=str(exc),
            )
        except Exception:
            logger.exception("trainer_service: failed to persist pretrain_checklist failure")
        return fallback_items

    output_json = result.get("output_json") or {}
    raw_items = output_json.get("items") or []
    items: list[dict[str, Any]] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        concept = str(entry.get("concept", "")).strip()
        materials = [str(m) for m in (entry.get("materials") or []) if str(m).strip()]
        if concept:
            items.append({"concept": concept, "materials": materials})

    validation_result = "pass" if result.get("output_json") else "fail"
    try:
        record_llm_call(
            call_purpose="pretrain_checklist",
            prompt_name=result["prompt_name"],
            prompt_version=result["prompt_version"],
            model=result["model"],
            input_text=input_text,
            latency_ms=result["latency_ms"],
            tokens_in=result["tokens_in"],
            tokens_out=result["tokens_out"],
            output_text=result.get("output_text"),
            output_json=output_json,
            retry_count=result["retry_count"],
            fallback_used=fallback_used,
            validation_result=validation_result,
        )
    except Exception:
        logger.exception("trainer_service: failed to record pretrain_checklist call")

    return items


def _build_render_context(
    topic: str,
    questions: list[BaselineQuestion],
    answers: list[str],
    scoring: ScoringResult | None,
    keywords: list[str],
    pretrain_checklist: list[dict[str, Any]],
    daily_minutes: int,
    total_weeks: int,
) -> dict[str, Any]:
    today = datetime.now().date().isoformat()
    overall = scoring.overall_level if scoring else "low"
    baseline_score = _BASELINE_SCORE_MAP.get(overall, 1.0)

    score_by_idx: dict[int, str] = {}
    if scoring is not None:
        for entry in scoring.scores:
            score_by_idx[entry.idx] = _SCORE_DISPLAY.get(entry.score, "☐ 未判定")

    questions_ctx: list[dict[str, Any]] = []
    for idx, question in enumerate(questions):
        answer = answers[idx] if idx < len(answers) else ""
        questions_ctx.append(
            {
                "question": question.question,
                "user_answer": answer,
                "score": score_by_idx.get(idx, "☐ 未判定"),
            }
        )

    units_ctx: list[dict[str, Any]] = [
        {
            "name": "基线诊断题",
            "questions": [
                {
                    "id": f"Q{idx + 1}",
                    "question": q.question,
                    "difficulty": q.difficulty,
                    "dimension": q.dimension,
                    "reference": q.reference_answer,
                    "status": "⬜ 未做",
                }
                for idx, q in enumerate(questions)
            ],
        }
    ]

    specialized_materials: list[dict[str, Any]] = [
        {
            "name": kw,
            "type": "文章",
            "difficulty": "⭐⭐",
            "hours": "1 h",
            "status": "未开始",
        }
        for kw in keywords[:5]
    ]

    return {
        "topic": topic,
        "created_at": today,
        "baseline_level": overall,
        "baseline_score": baseline_score,
        "background": "有接触",
        "goal_level": "专业",
        "daily_minutes": daily_minutes,
        "total_weeks": total_weeks,
        "scenario": "工作",
        "four_losses": {
            "多": False,
            "寡": False,
            "易": False,
            "止": False,
            "notes": "默认无明显四失问题；训练中持续观察。",
        },
        "zpd_known": ["（待补充）"],
        "zpd_target": ["（待补充）"],
        "zpd_unknown": ["（待补充）"],
        "weeks_plan": [
            {"weeks": "1-2", "desc": "打基础"},
            {"weeks": "3-4", "desc": "专题突破"},
            {"weeks": "5-8", "desc": "实战输出"},
            {"weeks": "9+", "desc": "精熟/创新"},
        ],
        "questions": questions_ctx,
        "mind_map_note": "[待补充知识面扫描]",
        "socratic_dialogue": "[对话记录]",
        "baseline_dim_scores": {
            "知识面": baseline_score,
            "深度": baseline_score,
            "量": baseline_score,
        },
        "pretrain_checklist": pretrain_checklist,
        "end_goal": f"掌握「{topic}」并能独立应用到真实场景",
        "stages": [
            {"name": "小成", "time": "1 月", "goal": f"理解{topic}的核心概念", "verification": "30 秒内说出 3 个核心知识点"},
            {"name": "中成", "time": "3 月", "goal": f"能独立完成{topic}相关实战任务", "verification": "输出 1 个可演示的产出"},
            {"name": "大成", "time": "6+ 月", "goal": f"对{topic}形成系统化认知与方法论", "verification": "能教别人入门"},
        ],
        "week_goals": [
            "完成关键词白名单覆盖的内容学习",
            "完成 5 道主动回忆题",
            "完成本周每日三省",
        ],
        "today_goals": [
            "阅读 03_资料库.md 第一节",
            "完成 1 道主动回忆题",
            "填写 08_每日反省.md 今日三省",
        ],
        "universal_materials": [
            {
                "name": f"《{topic} 入门到精通》",
                "type": "书",
                "difficulty": "⭐⭐",
                "hours": "20 h",
                "status": "未开始",
            }
        ],
        "specialized_materials": specialized_materials,
        "i1_materials": [],
        "principles": [
            "难度匹配：70% 懂、30% 不懂",
            "多模态：文字 + 图示 + 视频 + 实操",
            "可重复：经典 > 时效性资讯",
            "可验证：能通过练习/测试/项目确认是否掌握",
        ],
        "intervals": [1, 3, 7, 15, 30],
        "schedule_template": [
            {"slot": "早", "task": "回忆题", "duration": "10 min", "source": "05_主动回忆题.md"},
            {"slot": "午", "task": "新内容学习", "duration": "60 min", "source": "03_资料库.md"},
            {"slot": "晚", "task": "复盘 + 回忆", "duration": "15 min", "source": "08_每日反省.md"},
        ],
        "week_plans": [],
        "stage_phases": [
            {"weeks": "1-2", "theme": "基础", "phase": "入门"},
            {"weeks": "3-4", "theme": "专题 1", "phase": "进阶"},
            {"weeks": "5-8", "theme": "实战", "phase": "应用"},
            {"weeks": "9+", "theme": "创新", "phase": "精熟"},
        ],
        "units": units_ctx,
        "physical_space": "[图书馆/书房/咖啡馆]",
        "physical_avoid": "[床上/沙发 - 容易困]",
        "devices": ["[设备 1：笔记本电脑]", "[设备 2：降噪耳机]"],
        "light_temp": "自然光 / 22°C / 低噪音",
        "social_mentor": "无",
        "social_peers": "无",
        "social_family": "无",
        "info_distractions": [True, True, True],
        "info_quality": ["[书单 3-5 本]", "[Newsletter 1-2 个]", "[播客 1-2 个]"],
        "km_tools": "[Obsidian / Notion / Anki]",
        "env_checklist": [True, True, True, True],
        "extrinsic_material": [
            {"behavior": "完成每日任务", "reward": "[小礼物/奶茶/零食]", "timing": "当晚"},
            {"behavior": "完成周目标", "reward": "[一顿好饭]", "timing": "周末"},
            {"behavior": "完成阶段里程碑", "reward": "[一次旅行]", "timing": "阶段末"},
        ],
        "extrinsic_social": [
            "朋友圈分享成果（每周一次）",
            "给朋友/家人讲学到的东西",
            "写公众号/博客记录",
        ],
        "extrinsic_opportunity": [
            "[完成 X 阶段后可以解锁 Y 项目]",
            "[达成 Z 水平后可以申请 W 机会]",
        ],
        "intrinsic_competence": "任务难度 = 当前能力 + 1（i+1）",
        "intrinsic_autonomy": "每周给自己 1 小时\"自由探索\"时间",
        "intrinsic_relatedness": "找到 1-2 个学习伙伴 / 加入相关社群 / 给别人讲",
        "intrinsic_curiosity": "每周留 1 个\"为什么\"问题，深入研究",
        "intrinsic_meaning": f"我学「{topic}」是为了 ____",
        "reward_calendar": [
            {"trigger": "完成今日任务", "reward": "[具体]", "commit": "[签名]"},
            {"trigger": "完成周任务 80%", "reward": "[具体]", "commit": ""},
        ],
        "anti_patterns": [
            "物质奖励为主 → 失去内在动机",
            "延迟太久 → 当事人已忘",
            "错行为给奖励 → 强化错行为",
            "比较奖励（\"别人比你快\"）→ 削弱自我决定感",
            "只在失败时关注 → 回避训练",
        ],
        "monthly_review_questions": [
            "上月哪些奖励有效？",
            "哪些奖励已\"贬值\"？",
            "本月要尝试什么新奖励？",
            "内在 vs 外在比例是否合适（建议 7:3 内在:外在）？",
        ],
        "date": today,
        "three_reflections_template": ["忠于目标吗", "方法有效吗", "付诸实践了吗"],
        "scope_constraint": topic,
        "time_constraint_min": "90",
        "time_constraint_daily_max": "4-6",
        "rest_day": "周日",
        "goal_constraint": "阶段目标未达成前不开新坑",
        "method_constraint": "同时试的方法 ≤ 1 种（先跑 2 周看效果）",
        "stop_signals": [
            "**疲惫**：连续 3 天训练质量下降",
            "**厌倦**：对训练产生强烈抵触",
            "**伤害**：身体不适 / 心理压力过大",
            "**过拟合**：能完美回忆题但不会应用",
            "**完美主义**：因为\"不够完美\"而拖延",
        ],
        "rhythm_table": [
            {"phase": "紧", "state": "高强度（冲刺）", "duration": "1-2 周"},
            {"phase": "收", "state": "巩固消化", "duration": "1 周"},
            {"phase": "紧", "state": "高强度", "duration": "1-2 周"},
            {"phase": "收", "state": "巩固消化", "duration": "1 周"},
            {"phase": "放", "state": "自由探索 / 休息", "duration": "1 周"},
        ],
        "emergency_options": [
            "选项 A：完成 50% 任务 + 早睡",
            "选项 B：纯回忆（不学新内容）",
            "选项 C：直接休息（每周允许 1 次）",
        ],
        "give_up_protocol": [
            "回到 02_训练目标.md 的\"终点目标\"",
            "问自己：还想要那个目标吗？",
            "如想 → 调整节奏",
            "如不想 → 允许放弃，记录原因，重新选主题",
        ],
    }


def create_training(
    topic: str,
    *,
    training_root: str = ".",
    baseline_answers: list[str] | None = None,
    daily_minutes: int = 60,
    total_weeks: int = 3,
) -> DomainTraining:
    """Run the full new-training flow end-to-end and return a domain Training."""
    cleanup_target: Path | None = None
    training_id: int | None = None
    baseline_dir: Path | None = None

    try:
        # Step 1: validate topic
        try:
            validation: TopicValidationResult = validate_topic(topic, training_root=training_root)
        except Exception as exc:
            raise TrainerCreationError("validate_topic", exc) from exc
        if not validation.is_valid:
            suggestion_text = "; ".join(validation.suggestions) or validation.reason
            raise ValueError(
                f"主题不够具体：{validation.reason}。具体化建议：{suggestion_text}"
            )

        # Step 2: keywords
        try:
            keywords: KeywordResult = generate_keywords(topic, training_root=training_root)
        except Exception as exc:
            raise TrainerCreationError("generate_keywords", exc) from exc

        # Step 3: baseline questions
        try:
            baseline_questions: BaselineQuestions = generate_baseline_questions(
                topic=topic,
                keywords=keywords.keywords,
                must_cover_count=keywords.must_cover_count,
                forbidden=keywords.forbidden,
            )
        except Exception as exc:
            raise TrainerCreationError("generate_baseline_questions", exc) from exc

        # Step 4: score baseline (optional)
        scoring: ScoringResult | None = None
        if baseline_answers is not None:
            try:
                scoring = score_baseline(topic, baseline_questions.questions, baseline_answers)
            except Exception as exc:
                raise TrainerCreationError("score_baseline", exc) from exc

        overall_level = scoring.overall_level if scoring else "low"
        baseline_score_value = _BASELINE_SCORE_MAP.get(overall_level, 1.0)
        partial_topics = list(scoring.partial_topics) if scoring else []

        # Step 5: build context
        context = _build_render_context(
            topic=topic,
            questions=baseline_questions.questions,
            answers=list(baseline_answers) if baseline_answers else ["", "", ""],
            scoring=scoring,
            keywords=keywords.keywords,
            pretrain_checklist=[],
            daily_minutes=daily_minutes,
            total_weeks=total_weeks,
        )

        # Step 6: render files
        try:
            files = render_training_files(context)
        except Exception as exc:
            raise TrainerCreationError("render_training_files", exc) from exc

        # Step 7: dir name
        try:
            dir_name = sanitize_dir_name(topic)
        except Exception as exc:
            raise TrainerCreationError("sanitize_dir_name", exc) from exc

        # Step 8: writability
        try:
            root_path = Path(training_root).expanduser()
            if not check_writable(root_path):
                raise TrainerCreationError(
                    "check_writable",
                    OSError(f"training_root not writable: {root_path}"),
                )
        except TrainerCreationError:
            raise
        except Exception as exc:
            raise TrainerCreationError("check_writable", exc) from exc

        # Step 9: write files
        try:
            written_path = write_training_directory(root_path, dir_name, files)
            cleanup_target = written_path
        except Exception as exc:
            raise TrainerCreationError("write_training_directory", exc) from exc

        # Step 10: create training row
        now = _now_iso()
        targets_payload = {
            "end_goal": context["end_goal"],
            "stages": context["stages"],
        }
        schedule_payload = {
            "schedule_template": context["schedule_template"],
            "intervals": context["intervals"],
            "stage_phases": context["stage_phases"],
        }
        materials_payload = {
            "universal_materials": context["universal_materials"],
            "specialized_materials": context["specialized_materials"],
            "i1_materials": context["i1_materials"],
            "principles": context["principles"],
        }
        try:
            row = create_training_row(
                topic=topic,
                status="active" if baseline_answers else "created",
                keywords=keywords.keywords,
                must_cover_count=keywords.must_cover_count,
                forbidden=keywords.forbidden,
                directory=str(written_path),
                baseline_score=baseline_score_value,
                baseline_level=overall_level,
                targets=targets_payload,
                review_items=partial_topics,
                pretrain_checklist=[],
                schedule=schedule_payload,
                materials=materials_payload,
                created_at=now,
                last_active_at=now,
            )
            training_id = row.id
        except Exception as exc:
            raise TrainerCreationError("create_training", exc) from exc

        # Step 11: baseline history
        if scoring is not None and training_id is not None:
            try:
                add_baseline_history(
                    training_id=training_id,
                    score=baseline_score_value,
                    dimension_scores_json={
                        "scores": [
                            {"idx": s.idx, "score": s.score, "notes": s.notes}
                            for s in scoring.scores
                        ],
                        "overall_level": scoring.overall_level,
                        "partial_topics": scoring.partial_topics,
                    },
                )
            except Exception as exc:
                logger.exception("trainer_service: failed to record baseline_history")

        # Step 12: pretrain checklist for low baseline
        if overall_level == "low" and training_id is not None:
            try:
                weak_topics = partial_topics or [
                    q.question[:32] for q in baseline_questions.questions[:2]
                ]
                checklist = _generate_pretrain_checklist(
                    topic=topic,
                    keywords=keywords.keywords,
                    weak_topics=weak_topics,
                )
                if checklist:
                    update_training(
                        id=training_id,
                        pretrain_checklist=checklist,
                    )
            except Exception:
                logger.exception("trainer_service: failed to generate/update pretrain_checklist")

        # Step 13: build domain Training
        final_row = update_training(id=training_id, last_active_at=_now_iso()) if training_id else None
        effective_pretrain: list[dict[str, Any]] = []
        if final_row is not None:
            effective_pretrain = list(final_row.pretrain_checklist or [])
            review_items_list = list(final_row.review_items or [])
            keywords_list = list(final_row.keywords or keywords.keywords)
            forbidden_list = list(final_row.forbidden or keywords.forbidden)
            schedule_dict = final_row.schedule if isinstance(final_row.schedule, dict) else schedule_payload
            materials_dict = final_row.materials if isinstance(final_row.materials, dict) else materials_payload
            targets_dict = final_row.targets if isinstance(final_row.targets, dict) else targets_payload
        else:
            review_items_list = partial_topics
            keywords_list = keywords.keywords
            forbidden_list = keywords.forbidden
            schedule_dict = schedule_payload
            materials_dict = materials_payload
            targets_dict = targets_payload

        status_enum = (
            TrainingStatus.ACTIVE if baseline_answers else TrainingStatus.CREATED
        )
        level_enum = BaselineLevel(overall_level) if overall_level in {"high", "mid", "low"} else BaselineLevel.LOW

        domain = DomainTraining(
            id=training_id,
            topic=topic,
            status=status_enum,
            keywords=keywords_list,
            must_cover_count=keywords.must_cover_count,
            forbidden=forbidden_list,
            directory=cleanup_target or Path(),
            baseline_score=baseline_score_value,
            baseline_level=level_enum,
            targets=targets_dict,
            review_items=review_items_list,
            pretrain_checklist=effective_pretrain,
            schedule=schedule_dict,
            materials=materials_dict,
            current_week=1,
            last_review_at=None,
            created_at=datetime.fromisoformat(now),
            last_active_at=datetime.now(),
        )
        cleanup_target = None  # success → do not remove
        return domain

    except TrainerCreationError:
        _cleanup_dir(cleanup_target)
        raise
    except ValueError:
        _cleanup_dir(cleanup_target)
        raise
    except Exception as exc:
        _cleanup_dir(cleanup_target)
        raise TrainerCreationError("create_training", exc) from exc
    finally:
        baseline_dir = None  # placeholder hook for future cleanup


__all__ = ["TrainerCreationError", "create_training"]