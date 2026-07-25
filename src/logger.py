# logger.py
"""结构化日志：每一步 thought / action / observation 完整记录"""
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from config import LOGS_DIR

console = Console()


class AgentLogger:
    """简单但完整的日志系统"""

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.log_file = LOGS_DIR / f"agent_{session_id}.log"
        self.steps: list[dict] = []

    def _write(self, level: str, content: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {content}\n"
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(line)

    def thought(self, content: str) -> None:
        """记录思考过程"""
        self._write("THOUGHT", content)
        self.steps.append({"type": "thought", "content": content})
        console.print(Panel(content, title="[bold blue]Thought[/bold blue]", border_style="blue"))

    def action(self, content: str) -> None:
        """记录行动"""
        self._write("ACTION", content)
        self.steps.append({"type": "action", "content": content})
        console.print(Panel(content, title="[bold yellow]Action[/bold yellow]", border_style="yellow"))

    def observation(self, content: str) -> None:
        """记录观察结果"""
        self._write("OBSERVATION", content)
        self.steps.append({"type": "observation", "content": content})
        console.print(Panel(content, title="[bold green]Observation[/bold green]", border_style="green"))

    def info(self, content: str) -> None:
        self._write("INFO", content)
        console.print(f"[cyan]{content}[/cyan]")

    def error(self, content: str) -> None:
        self._write("ERROR", content)
        console.print(f"[bold red]ERROR: {content}[/bold red]")

    def success(self, content: str) -> None:
        self._write("SUCCESS", content)
        console.print(f"[bold green]✓ {content}[/bold green]")