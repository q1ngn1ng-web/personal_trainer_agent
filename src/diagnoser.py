# diagnoser.py
"""基线诊断模块 —— 生成问题 + 评估水平"""
from typing import List
from models import DiagnosisQuestion, BaselineResult, UserProfile


class Diagnoser:
    """根据主题生成诊断题并评估用户基线"""

    def generate_questions(self, theme: str) -> List[DiagnosisQuestion]:
        """生成 3 道有区分度的前置诊断题"""
        theme_lower = theme.lower()

        # Python / 编程相关硬编码高质量题目
        if any(k in theme_lower for k in ["python", "编程", "自动化", "脚本"]):
            return [
                DiagnosisQuestion(
                    question="Python 中 list 和 tuple 的核心区别是什么？（一句话回答）",
                    reference_answer="list 可变（mutable），tuple 不可变（immutable）",
                    category="基础语法"
                ),
                DiagnosisQuestion(
                    question="写一段代码，用 for 循环打印 1 到 10 之间的所有偶数。",
                    reference_answer="for i in range(1, 11):\n    if i % 2 == 0:\n        print(i)",
                    category="基础语法"
                ),
                DiagnosisQuestion(
                    question="requests 库主要用来做什么？请用一句话说明。",
                    reference_answer="发送 HTTP 请求（GET/POST 等），与网络 API 交互",
                    category="常用库"
                ),
            ]

        # 英语相关
        if any(k in theme_lower for k in ["英语", "雅思", "托福", "english"]):
            return [
                DiagnosisQuestion(
                    question="请用英语简单介绍你自己（2-3 句话）。",
                    reference_answer="任意语法基本正确的自我介绍",
                    category="口语表达"
                ),
                DiagnosisQuestion(
                    question="present perfect 和 simple past 的核心区别是什么？",
                    reference_answer="present perfect 强调对现在的影响或未明确时间，simple past 强调过去完成的动作",
                    category="语法"
                ),
                DiagnosisQuestion(
                    question="你目前的英语阅读速度大概是多少（词/分钟）？或者你最近读过什么英文材料？",
                    reference_answer="任意具体回答",
                    category="阅读能力"
                ),
            ]

        # 通用兜底题目（适用于任意主题）
        return [
            DiagnosisQuestion(
                question=f"关于「{theme}」，请说出你目前最熟悉的 3 个核心概念或术语。",
                reference_answer="能说出 3 个相关概念即为有基础",
                category="知识面"
            ),
            DiagnosisQuestion(
                question=f"请举一个「{theme}」在实际工作或生活中的具体应用例子。",
                reference_answer="能给出具体场景即为有实践意识",
                category="应用"
            ),
            DiagnosisQuestion(
                question=f"你觉得学习「{theme}」目前最大的难点或卡点是什么？",
                reference_answer="任意真实回答",
                category="元认知"
            ),
        ]

    def evaluate(
        self,
        questions: List[DiagnosisQuestion],
        answers: List[str],
        profile: UserProfile
    ) -> BaselineResult:
        """
        评估基线。
        v0.1 使用规则评分（后续可替换为 LLM 评分）。
        评分逻辑：
        - 答案长度 > 15 字 且 非纯“不知道/不会” → 计 1 分
        - 最终 0-1 分 = 低，2 分 = 中，3 分 = 高
        """
        score = 0
        pre_training = []

        for i, (q, a) in enumerate(zip(questions, answers)):
            a_clean = a.strip().lower()
            if len(a_clean) < 8 or a_clean in ["不知道", "不会", "没学过", "不清楚", "no idea"]:
                pre_training.append(q.category)
            else:
                score += 1

        if score >= 3:
            level = "高"
        elif score == 2:
            level = "中"
        else:
            level = "低"

        notes = f"用户背景：{profile.background}，目标：{profile.target_level}。诊断得分 {score}/3。"

        return BaselineResult(
            level=level,
            answers=answers,
            score=score,
            pre_training_needed=list(set(pre_training)),
            diagnosis_notes=notes
        )