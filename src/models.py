# models.py
"""所有 Pydantic 数据模型"""
from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class UserProfile(BaseModel):
    """用户画像 —— 对象档案核心"""
    theme: str = Field(..., description="训练主题，必须具体到可验证")
    background: Literal["零基础", "有过接触", "已有基础"] = Field(..., description="当前背景")
    target_level: Literal["业余", "专业", "专家", "大师"] = Field(..., description="目标水平")
    daily_time: int = Field(..., gt=0, description="每天可投入分钟数")
    total_weeks: int = Field(..., gt=0, description="总投入周数")
    application: str = Field(..., description="应用场景：工作/兴趣/考试/副业等")


class DiagnosisQuestion(BaseModel):
    """单道诊断题"""
    question: str
    reference_answer: str  # 内部判断用，不直接展示给用户
    category: str = "基础"


class BaselineResult(BaseModel):
    """基线诊断结果"""
    level: Literal["低", "中", "高"]
    answers: List[str]
    score: int = Field(..., ge=0, le=3, description="答对题数（0-3）")
    pre_training_needed: List[str] = Field(default_factory=list, description="需要预训练的概念")
    diagnosis_notes: str = ""


class TrainingSession(BaseModel):
    """一次完整的训练会话记录"""
    session_id: str
    theme: str
    background: str
    target_level: str
    daily_time: int
    total_weeks: int
    application: str
    baseline_level: str
    workspace_path: str
    created_at: datetime
    updated_at: datetime
    status: Literal["active", "paused", "completed"] = "active"