"""历史用例 Excel 解析器。

依赖：pandas + openpyxl（项目已有；若未装，调用方应捕获 ImportError）。
关键不变量：
  - 步骤数组与预期数组按编号对齐；不齐时保留所有步骤和预期结果 + 写 warning
  - 子项的阶段后缀单独抽 stage 字段
  - 未映射的列放到 extra dict
  - file_id 由调用方传入（来自字节内容 sha1），保证幂等
"""
from __future__ import annotations

import re
from pathlib import Path

from backend.core.legacy._hash import file_content_id
from backend.schemas.column_mapping import (
    DEFAULT_STAGE_SUFFIXES,
    ColumnMapping,
)
from backend.schemas.legacy_case import LegacyCase, LegacyCaseStep
from backend.schemas.parse_warning import ParseWarning


# 步骤/预期 单元格内换行 + 编号识别
_NUM_PREFIX_RE = re.compile(
    r"""^\s*
        (?:
            \d+\s*[\.\)、]    # 1. 1) 1、
            | [①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]
            | [一二三四五六七八九十]+\s*[、\.]
            | Step\s*\d+\s*[:：]
        )
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _split_numbered_lines(text: str) -> list[str]:
    """按行 + 编号前缀拆分。空字符串返回空列表。"""
    if text is None:
        return []
    s = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return []
    raw_lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
    out: list[str] = []
    for ln in raw_lines:
        cleaned = _NUM_PREFIX_RE.sub("", ln).strip()
        if cleaned:
            out.append(cleaned)
        elif out:
            # 编号空行：跳过
            continue
        else:
            out.append(ln)
    return out


def _split_stage(sub_item: str, suffixes: list[str]) -> tuple[str, str | None]:
    """子项 -> (base, stage)。后缀模式：以 - 或 _ 或空白连接的尾词。"""
    if not sub_item:
        return "", None
    s = sub_item.strip()
    # 优先匹配最长后缀
    for suf in sorted(suffixes, key=len, reverse=True):
        for sep in ["-", "—", "_", " ", "·"]:
            tail = f"{sep}{suf}"
            if s.endswith(tail):
                return s[: -len(tail)].strip(), suf
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)].strip().rstrip("-—_·"), suf
    return s, None


def parse_excel(
    path: Path,
    mapping: ColumnMapping,
    stage_suffixes: list[str] | None = None,
    sheet_name: str | None = None,
    file_id: str | None = None,
) -> tuple[list[LegacyCase], list[str], list[ParseWarning]]:
    """解析 Excel 文件。

    Parameters
    ----------
    file_id : str, optional
        调用方传入的内容 hash；不传则现场计算（仅在测试 / 离线脚本场景下）。

    Returns
    -------
    (cases, sheet_names, warnings)
    """
    import pandas as pd  # 延迟导入，便于无 pandas 环境的纯 schema 测试

    warnings: list[ParseWarning] = []
    suffixes = stage_suffixes or list(DEFAULT_STAGE_SUFFIXES)
    fid = file_id or file_content_id(path)

    xl = pd.ExcelFile(path)
    sheet_names = list(xl.sheet_names)
    sheets_to_read = [sheet_name] if sheet_name and sheet_name in sheet_names else sheet_names

    # 反向索引：标准列 -> 表头原文（首个命中）
    std_to_raw: dict[str, str] = {}
    for raw_h, std in mapping.header_to_standard.items():
        if std and std not in std_to_raw:
            std_to_raw[std] = raw_h

    cases: list[LegacyCase] = []

    for sn in sheets_to_read:
        df = xl.parse(sn, dtype=str)
        if df.empty:
            warnings.append(ParseWarning(
                level="info", code="EXCEL_SHEET_EMPTY",
                message=f"Sheet {sn!r} 为空", sheet=sn,
            ))
            continue

        # 行号：表头是第 1 行，第一条数据是第 2 行
        for i, row in df.iterrows():
            row_no = int(i) + 2

            def cell(std_col: str) -> str:
                raw = std_to_raw.get(std_col)
                if not raw or raw not in df.columns:
                    return ""
                v = row.get(raw, "")
                if v is None or (isinstance(v, float) and v != v):  # NaN
                    return ""
                return str(v).strip()

            title = cell("用例名称")
            if not title:
                continue  # 空行跳过

            steps_raw = _split_numbered_lines(cell("用例步骤"))
            expected_raw = _split_numbered_lines(cell("预期结果"))

            n = max(len(steps_raw), len(expected_raw))
            # 不再产生警告，步骤和预期数量不一致是正常情况

            steps_aligned: list[LegacyCaseStep] = []
            for k in range(n):
                # 当步骤数多于预期数时，预期结果对齐到步骤的最后几步
                # 例如：步骤有4个，预期有2个，则预期的第1个对齐步骤的第3个，预期的第2个对齐步骤的第4个
                expected_index = k - (len(steps_raw) - len(expected_raw)) if len(steps_raw) > len(expected_raw) else k
                
                steps_aligned.append(LegacyCaseStep(
                    index=k + 1,
                    action=steps_raw[k] if k < len(steps_raw) else "",
                    expected=expected_raw[expected_index] if (0 <= expected_index < len(expected_raw)) else "",
                ))
            # 仅有预期、无步骤的退化情况：保留 1 条空 action
            if not steps_aligned and expected_raw:
                steps_aligned = [LegacyCaseStep(
                    index=1, action="", expected="\n".join(expected_raw),
                )]

            sub_item = cell("子项")
            sub_base, stage = _split_stage(sub_item, suffixes)

            mapped_raw = {raw for raw, std in mapping.header_to_standard.items() if std}
            extra: dict = {}
            for col in df.columns:
                if col not in mapped_raw:
                    val = row.get(col, "")
                    if val is None or (isinstance(val, float) and val != val):
                        continue
                    sval = str(val).strip()
                    if sval:
                        extra[col] = sval

            cases.append(LegacyCase(
                case_id=f"LC_{fid}_{row_no:04d}",
                suite=cell("用例目录"),
                module=cell("模块"),
                sub_item=sub_item,
                sub_item_base=sub_base,
                stage=stage,
                title=title,
                preconditions=cell("前置条件"),
                steps=steps_aligned,
                case_type=cell("用例类型"),
                priority=cell("用例等级"),
                creator=cell("创建人"),
                source_file=path.name,
                source_row=row_no,
                extra=extra,
            ))

    return cases, sheet_names, warnings
