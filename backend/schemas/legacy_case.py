"""历史用例（Legacy Case）数据模型。

来源：用户上传的历史 .xlsx / .xls 测试用例。
解析后落 memory/<project>/legacy/cases.json。

设计要点：
  - 步骤与预期保持索引对齐（解析器层强保证）
  - 子项的阶段后缀（如 "-前置准备"）单独抽出 stage 字段
  - 不强制 priority 取值，团队可能使用非 P0~P3 体系
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from backend.schemas.parse_warning import ParseWarning


class LegacyCaseStep(BaseModel):
    """一条用例步骤 + 预期，索引对齐。"""
    index: int                              # 1-based
    action: str
    expected: str = ""                      # 允许空（部分团队预期合并写在结尾）


class LegacyCase(BaseModel):
    """历史用例的标准化表示。"""
    case_id: str                            # 解析时由后端生成：LC_<file_hash6>_<row:04d>
    suite: str = ""                         # 用例目录（顶级归类）
    module: str = ""                        # 一级模块
    sub_item: str = ""                      # 二级子项原文（含阶段后缀）
    sub_item_base: str = ""                 # 二级子项去掉阶段后缀的纯名
    stage: Optional[str] = None             # 阶段：前置准备 / 正常流程 / 异常流程 / ...
    title: str                              # 用例名称（"场景-预期" 格式预期）
    preconditions: str = ""
    steps: list[LegacyCaseStep] = Field(default_factory=list)
    case_type: str = ""                     # 功能测试 / 接口测试 / 性能测试 / ...
    priority: str = ""                      # 团队原文：P0/P1/P2/P3 或其他
    creator: str = ""
    source_file: str                        # 上传的原始文件名
    source_row: int                         # 原 Excel 行号（1-based 含表头）
    extra: dict = Field(default_factory=dict)  # 未映射的额外列


class LegacyCaseFile(BaseModel):
    """已解析的一份历史用例文件的元信息。"""
    file_id: str                            # 文件级唯一 ID，sha1[:8]
    name: str
    ext: str
    size: int
    mtime: float
    uploaded_at: str
    case_count: int
    sheet_names: list[str] = Field(default_factory=list)
    column_mapping_used: dict = Field(default_factory=dict)
    parse_warnings: list[ParseWarning] = Field(default_factory=list)
    analyzed: bool = False                  # 是否已通过五阶段分析
    analyzed_at: Optional[str] = None       # 最后分析时间（ISO8601）
