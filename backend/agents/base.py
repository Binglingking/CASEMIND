from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.config import settings


def load_prompt(name: str) -> str:
    """加载 prompts 目录下的模板。

    支持：
      - 平铺文件名： "testcase.txt"
      - 子目录路径： "case_gen/01_slicer.txt" 或 "extract/knowledge_points.txt"
    """
    # Path / 运算符天然支持 "a/b" 形式的相对路径
    p: Path = settings.prompts_dir / name
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


class AgentBase:
    name: str = "agent"

    def __init__(self, project: str):
        self.project = project
