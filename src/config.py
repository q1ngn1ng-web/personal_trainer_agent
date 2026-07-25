# config.py
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
PROMPTS_DIR = PROJECT_ROOT / "prompts"
LOGS_DIR = PROJECT_ROOT / "logs"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "trainer.db"

# 确保目录存在
for d in [PROMPTS_DIR, DATA_DIR, WORKSPACE_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# LLM 配置（OpenAI-compatible）
LLM_API_BASE = os.getenv("DEEPSEEK_API_BASE")  # 或 deepseek / grok / ollama
LLM_API_KEY = os.getenv("DEEPSEEK_API_KEY")  # 替换
LLM_MODEL = os.getenv("DEEPSEEK_MODEL")  # 或 deepseek-chat 等

# ReAct 相关（v0.2 使用）
MAX_REACT_STEPS: int = 10
MAX_RETRIES: int = 3
TIMEOUT_SECONDS: int = 30

def load_system_prompt() -> str:
    """热加载 System Prompt，支持运行时修改 prompts/system_prompt.txt"""
    prompt_path = PROMPTS_DIR / "system_prompt.txt"
    if not prompt_path.exists():
        # 默认 Prompt
        default = """你是一个严格遵循「训练之道·十要素完整闭环 v3」的个人训练师 Agent。
        你的职责是：诊断用户真实水平 → 生成高度定制的训练文件包 → 维护长期记忆。
        永远用中文回复，内容必须具体、可量化、可执行。
        不要给空模板，必须根据用户主题和基线动态调整。"""
        prompt_path.write_text(default, encoding="utf-8")
        return default
    return prompt_path.read_text(encoding="utf-8")