"""Excel 列同义词 → 标准列名 映射。

每个项目独立持久化到 memory/<project>/legacy/column_mapping.json。
首次上传一份新结构的 Excel 时由用户在 UI 上确认一次，之后自动套用。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


# 标准列名集合（团队模板）
STANDARD_COLUMNS = [
    "用例目录",
    "模块",
    "子项",
    "用例名称",
    "前置条件",
    "用例步骤",
    "预期结果",
    "用例类型",
    "用例等级",
    "创建人",
]


# 内置同义词字典；用户可在 Settings 中扩展但不能减小
DEFAULT_SYNONYMS: dict[str, list[str]] = {
    "用例目录": ["用例目录", "目录", "一级目录", "Suite", "Folder", "测试目录"],
    "模块":   ["模块", "功能模块", "Module", "所属模块"],
    "子项":   ["子项", "二级模块", "子模块", "SubModule", "二级子项", "功能点"],
    "用例名称": ["用例名称", "用例标题", "标题", "Title", "Case Name", "Case", "用例"],
    "前置条件": ["前置条件", "前置", "Pre-condition", "Precondition", "Pre"],
    "用例步骤": ["用例步骤", "步骤", "操作步骤", "Steps", "Step"],
    "预期结果": ["预期结果", "预期", "期望结果", "Expected", "Expected Result"],
    "用例类型": ["用例类型", "类型", "Type", "测试类型"],
    "用例等级": ["用例等级", "优先级", "等级", "Priority", "Level"],
    "创建人":  ["创建人", "作者", "Author", "Created By", "Owner"],
}


# 用例步骤/预期结果 单元格内拆分时识别的"阶段后缀"模式（先匹配长后缀）
DEFAULT_STAGE_SUFFIXES = [
    "前置准备",
    "正常流程",
    "异常流程",
    "边界情况",
    "兼容性",
    "安全性",
    "性能",
]


class ColumnMapping(BaseModel):
    """单份 Excel 文件的列映射结果。"""
    # 表头原文 → 标准列名（标准列名为空字符串表示忽略该列）
    header_to_standard: dict[str, str] = Field(default_factory=dict)
    # 解析时识别的额外列（标准列名为空的那些）名单，便于 UI 展示
    unmapped_headers: list[str] = Field(default_factory=list)
    # 用户是否已在 UI 上确认；False 表示是 AI/同义词推断结果
    confirmed: bool = False
    # 命中率：标准列被映射上的比例（0~1）
    hit_ratio: float = 0.0


class ProjectColumnMappingStore(BaseModel):
    """项目级持久化结构。

    fingerprint = 表头原文按字母序拼接后的 sha1[:12]，相同表头的不同文件复用同一份映射。
    """
    by_fingerprint: dict[str, ColumnMapping] = Field(default_factory=dict)
    stage_suffixes: list[str] = Field(default_factory=lambda: list(DEFAULT_STAGE_SUFFIXES))
    extra_synonyms: dict[str, list[str]] = Field(default_factory=dict)
