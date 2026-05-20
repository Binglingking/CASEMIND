"""结构化解析警告。

替换 list[str] —— 前端上传报告需要按 level/code 过滤、按 row/sheet 跳转。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


WarningLevel = Literal["info", "warning", "error"]


# 已知 code 集合（只用于文档/前端 i18n，不强制 enum 校验，便于灰度新增）
KNOWN_CODES = [
    # excel
    "STEPS_EXPECTED_MISMATCH",     # 步骤数与预期数不一致
    "EMPTY_TITLE_ROW",             # 空标题行被跳过
    "EMPTY_STEPS",                 # 步骤为空
    "EXCEL_SHEET_EMPTY",           # 整个 sheet 为空
    # xmind
    "XMIND_OLD_XML_FORMAT",        # 老版 content.xml 不支持
    "XMIND_MISSING_ROOT",          # 缺 rootTopic
    "DUPLICATE_NODE_PATH",         # MD 重复节点路径
    "INVALID_DEPTH_JUMP",          # MD 层级跳跃
    # ingest
    "ALREADY_PARSED_IDEMPOTENT",   # 同字节内容已存在，跳过解析
]


class ParseWarning(BaseModel):
    level: WarningLevel = "warning"
    code: str
    message: str
    sheet: Optional[str] = None
    row: Optional[int] = None
    column: Optional[str] = None
    node_path: list[str] = Field(default_factory=list)
