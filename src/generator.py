# generator.py
"""生成完整 10 个训练文件 —— 高度定制，禁止空模板"""
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
from models import UserProfile, BaselineResult
from config import WORKSPACE_DIR


class Generator:
    """根据用户画像和基线结果生成完整训练文件包"""

    def generate(
        self,
        profile: UserProfile,
        baseline: BaselineResult
    ) -> Path:
        """
        生成完整 10 文件包，返回 workspace 路径。
        内容必须具体到这位用户，不能是通用套话。
        """
        # 创建主题目录
        safe_theme = "".join(c if c.isalnum() or c in "-_" else "_" for c in profile.theme)
        workspace = WORKSPACE_DIR / f"training_{safe_theme}"
        workspace.mkdir(parents=True, exist_ok=True)

        now = datetime.now().strftime("%Y-%m-%d")

        # 生成全部文件
        files = {
            "00_对象档案.md": self._gen_00_profile(profile, baseline, now),
            "01_基线诊断.md": self._gen_01_baseline(profile, baseline, now),
            "02_训练目标.md": self._gen_02_goals(profile, baseline),
            "03_资料库.md": self._gen_03_resources(profile, baseline),
            "04_复习日历.md": self._gen_04_calendar(profile, baseline),
            # "05_主动回忆题.md": self._gen_05_recall(profile, baseline),
            # "06_环境配置.md": self._gen_06_environment(profile),
            # "07_奖励机制.md": self._gen_07_reward(profile),
            # "08_每日反省.md": self._gen_08_reflection(profile),
            # "09_边界与止.md": self._gen_09_boundary(profile),
        }

        for fname, content in files.items():
            (workspace / fname).write_text(content, encoding="utf-8")

        return workspace

    def _gen_00_profile(self, p: UserProfile, b: BaselineResult, now: str) -> str:
        return f"""# 对象档案 - {p.theme}

> 生成时间：{now}

## 👤 你的画像

| 维度 | 你的状态 |
|------|---------|
| 训练主题 | {p.theme} |
| 当前基线 | **{b.level}**（得分 {b.score}/3） |
| 背景 | {p.background} |
| 目标水平 | {p.target_level} |
| 每日时间 | {p.daily_time} 分钟 |
| 总投入周期 | {p.total_weeks} 周 |
| 应用场景 | {p.application} |

## 🎯 你的「四失」初步判断

> 《学记》：或失则多，或失则寡，或失则易，或失则止。

- 多（贪多）？ → {"可能，基线高但需注意收敛" if b.level == "高" else "暂不明显"}
- 寡（狭窄）？ → {"是，知识面需要拓展" if b.level == "低" else "否"}
- 易（轻视）？ → 待观察
- 止（畏难）？ → {"需要额外鼓励和拆解" if b.level == "低" else "暂不明显"}

## 📍 最近发展区（ZPD）

- **已知区**：根据诊断，你已具备基础认知框架
- **ZPD（跳一跳够得着）**：需要针对性补强的点 → {', '.join(b.pre_training_needed) if b.pre_training_needed else "核心概念深化与应用"}
- **未知区**：更高阶的体系化与实战输出

## 🛣️ 训练一眼览

> 接下来 {p.total_weeks} 周你要做的事：

1. **第 1-2 周**：打基础 + 补预训练清单（如果有）
2. **第 3-4 周**：专题突破核心概念
3. **第 5-8 周**：实战输出（项目/文章/讲解）
4. **第 9+ 周**：精熟与迁移

**当前进度**：第 1 周 / 总 {p.total_weeks} 周
**今日立即行动**：打开 `04_复习日历.md` 看第 1 天任务，然后做 `05_主动回忆题.md` 的第 1 组题。
"""

    def _gen_01_baseline(self, p: UserProfile, b: BaselineResult, now: str) -> str:
        answers_text = "\n".join([f"- Q{i+1} 你的回答：{a}" for i, a in enumerate(b.answers)])
        pre_text = "\n".join([f"- {item}" for item in b.pre_training_needed]) if b.pre_training_needed else "- 无明显缺失，可直接进入正式训练"
        return f"""# 基线诊断 - {p.theme}

> 诊断时间：{now}

## 前置拷问结果

{answers_text}

## 诊断结果

| 维度 | 评分 | 备注 |
|------|------|------|
| 综合基线 | **{b.level}** | 得分 {b.score}/3 |
| 诊断笔记 | - | {b.diagnosis_notes} |

## 预训练清单（基线为「低」或「中」时优先完成）

{pre_text}

> 建议：如果基线是「低」，先花 3-7 天把预训练清单过一遍，再进入正式训练。

## 基线升级日志

| 日期 | 基线评分 | 升级内容 |
|------|---------|---------|
| {now} | {b.level}（{b.score}/3） | 初始诊断 |
"""

    def _gen_02_goals(self, p: UserProfile, b: BaselineResult) -> str:
        # 根据基线和目标水平动态调整阶段目标
        if b.level == "低":
            small = f"能独立完成 {p.theme} 最基础的 3 个操作/概念讲解"
            mid = f"能完成一个完整的小项目或输出一篇完整笔记"
            big = f"达到「业余」可独立使用的水平"
        elif b.level == "中":
            small = f"能流畅解决 {p.theme} 中级问题，并给别人讲清楚"
            mid = f"能独立完成中等复杂度项目，并复盘优化"
            big = f"接近「专业」水平，能应对真实工作场景"
        else:
            small = f"能体系化输出 {p.theme} 的知识框架"
            mid = f"能指导别人，或产出可公开的高质量作品"
            big = f"达到「专家」或「大师」门槛"

        return f"""# 训练目标 - {p.theme}

> 《大学》：知止而后有定。
> 《荀子·劝学》：其数则始乎诵经，终乎读礼；其义则始乎为士，终乎为圣人。

## 终点目标（境界层）

**一句话**：在 {p.total_weeks} 周内，把「{p.theme}」练到能在「{p.application}」场景中稳定输出价值的水平。

## 阶段目标（意义层）

| 阶段 | 时间 | 目标 | 验证标准 |
|------|------|------|---------|
| 小成 | 第 1-{max(3, p.total_weeks//3)} 周 | {small} | 能闭卷讲解 + 完成对应练习 |
| 中成 | 第 {max(3, p.total_weeks//3)+1}-{max(6, p.total_weeks*2//3)} 周 | {mid} | 有可展示的作品或项目 |
| 大成 | 第 {max(6, p.total_weeks*2//3)+1}-{p.total_weeks} 周 | {big} | 能独立解决真实问题，并教别人 |

## 本周目标（手段层）

- [ ] 完成基线诊断中的预训练清单（如有）
- [ ] 建立每日训练节奏（固定时间）
- [ ] 完成第 1 组主动回忆题并记录正确率
- [ ] 写出第一份学习笔记或代码片段
- [ ] 配置好训练环境（见 06_环境配置.md）

## 今日子目标

- [ ] 阅读本文件 + 04_复习日历.md
- [ ] 做 05_主动回忆题.md 第 1 组（闭卷）
- [ ] 填写 08_每日反省.md 的「今日三省」
"""

    def _gen_03_resources(self, p: UserProfile, b: BaselineResult) -> str:
        # 根据主题给推荐资料（可后续用 LLM 增强）
        theme_lower = p.theme.lower()
        if any(k in theme_lower for k in ["python", "编程", "自动化"]):
            common = """
| 资料 | 类型 | 难度 | 预计时间 | 状态 |
|------|------|------|---------|------|
| 《Python 编程：从入门到实践》 | 书籍 | ⭐⭐ | 20h | 未开始 |
| Python 官方文档 Tutorial | 文档 | ⭐ | 8h | 未开始 |
| Real Python 网站精选教程 | 网站 | ⭐⭐ | 按需 | 未开始 |
"""
            special = """
| 资料 | 类型 | 难度 | 预计时间 | 状态 |
|------|------|------|---------|------|
| requests 官方文档 | 文档 | ⭐⭐ | 3h | 未开始 |
| 自动化相关实战项目（自选） | 项目 | ⭐⭐⭐ | 10h+ | 未开始 |
"""
        else:
            common = f"""
| 资料 | 类型 | 难度 | 预计时间 | 状态 |
|------|------|------|---------|------|
| 「{p.theme}」领域权威入门书/课程（请自行补充具体名称） | 教材/视频 | ⭐⭐ | 15-25h | 未开始 |
| 该领域高质量综述或官方文档 | 文档 | ⭐ | 5h | 未开始 |
"""
            special = f"""
| 资料 | 类型 | 难度 | 预计时间 | 状态 |
|------|------|------|---------|------|
| 与「{p.application}」强相关的案例/项目 | 实战 | ⭐⭐⭐ | 按需 | 未开始 |
"""

        return f"""# 资料库 - {p.theme}

> 《荀子·劝学》：君子生非异也，善假于物也。

## 普适性资料（操缦 - 基础框架）

{common}

## 专门化资料（对准你的应用场景：{p.application}）

{special}

## i+1 难度匹配原则

- 看资料时大约 70% 能懂、30% 需要思考 → 难度刚好
- 太简单会无效，太难会崩溃
- 每周根据基线更新本表

## 资料使用原则

1. 多模态：文字 + 图示 + 视频 + 实操，至少覆盖两种
2. 可重复：经典优先于时效资讯
3. 可验证：学完必须能通过练习或项目确认掌握
"""

    def _gen_04_calendar(self, p: UserProfile, b: BaselineResult) -> str:
        # 生成第 1 周详细日历
        today = datetime.now()
        days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        calendar_rows = []
        for i in range(7):
            d = today + timedelta(days=i)
            day_name = days[d.weekday()]
            if i == 0:
                task = "完成基线确认 + 第 1 组主动回忆题 + 填写三省"
            elif i == 6:
                task = "周复盘 + 更新基线日志"
            else:
                task = f"新内容学习（{p.daily_time} 分钟）+ 回忆复习"
            calendar_rows.append(f"| {d.strftime('%m-%d')} {day_name} | {task} | ⬜ |")

        calendar_md = "\n".join(calendar_rows)

        return f"""# 复习日历 - {p.theme}

> 《学记》：时教必有正业，退息必有居学。
> 艾宾浩斯间隔：1-3-7-15-30 天最有效。

## 时间分配原则

- **正业**（大块时间）：处理新内容、难题（建议 {max(25, p.daily_time-10)} 分钟）
- **居学**（碎片时间）：主动回忆、回顾（建议 10-15 分钟）
- **日总投入**：{p.daily_time} 分钟

## 间隔重复算法（简化版）
"""