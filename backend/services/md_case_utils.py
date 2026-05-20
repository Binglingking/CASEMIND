"""Utilities for converting test cases between dict list and Markdown table format."""
from __future__ import annotations

import re

HEADERS = ["序号", "目录", "模块", "子项", "用例名称", "前置条件", "用例步骤", "预期结果", "优先级", "类型"]
_SPLIT_COLS = {"前置条件", "用例步骤", "预期结果"}


def _esc(s: str) -> str:
    return str(s).replace("|", "｜").replace("\n", " ").strip()


def cases_to_md(cases: list[dict], title: str = "测试用例") -> str:
    lines = [f"# {title}\n"]
    lines.append("| " + " | ".join(HEADERS) + " |")
    lines.append("| " + " | ".join(["---"] * len(HEADERS)) + " |")

    for i, c in enumerate(cases, 1):
        steps = c.get("steps", [])
        if isinstance(steps, list):
            parts = []
            for j, s in enumerate(steps):
                if isinstance(s, dict):
                    text = f"{s.get('action', '')} {s.get('data', '')}".strip()
                else:
                    text = str(s)
                parts.append(f"{j + 1}.{text}")
            step_text = " ".join(parts)
        else:
            step_text = str(steps)

        pre = c.get("preconditions", "")
        if isinstance(pre, list):
            pre_text = " ".join(f"{j + 1}.{p}" for j, p in enumerate(pre))
        else:
            pre_text = str(pre)

        row = [
            str(i),
            c.get("catalog", ""),
            c.get("module", ""),
            c.get("sub_item", ""),
            c.get("name") or c.get("title", ""),
            pre_text,
            step_text,
            c.get("expected_result") or c.get("expected", ""),
            c.get("priority", ""),
            c.get("category") or c.get("type", ""),
        ]
        lines.append("| " + " | ".join(_esc(v) for v in row) + " |")

    return "\n".join(lines) + "\n"


def md_to_cases(md: str) -> list[dict]:
    """Parse a Markdown table into a list of case dicts for UI display."""
    table_lines = [l.strip() for l in md.split("\n") if l.strip().startswith("|")]
    if len(table_lines) < 3:
        return []

    headers = [h.strip() for h in table_lines[0].split("|")[1:-1]]
    cases = []

    for row_line in table_lines[2:]:
        cells = [c.strip() for c in row_line.split("|")[1:-1]]
        if len(cells) < len(headers):
            continue
        rd = dict(zip(headers, cells))

        step_text = rd.get("用例步骤", "")
        steps = [s.strip() for s in re.split(r"(?:^|\s+)\d+\.", step_text) if s.strip()]

        cases.append({
            "catalog": rd.get("目录", ""),
            "module": rd.get("模块", ""),
            "sub_item": rd.get("子项", ""),
            "name": rd.get("用例名称", ""),
            "title": rd.get("用例名称", ""),
            "preconditions": rd.get("前置条件", ""),
            "steps": steps,
            "expected": rd.get("预期结果", ""),
            "expected_result": rd.get("预期结果", ""),
            "priority": rd.get("优先级", ""),
            "category": rd.get("类型", ""),
            "type": rd.get("类型", ""),
            "source_refs": [],
        })

    return cases


def split_numbered(text: str) -> str:
    """'1.a 2.b 3.c' → '1.a\n2.b\n3.c' (for Excel wrap_text cells)."""
    if not text:
        return text
    return re.sub(r"\s+(\d+\.)", r"\n\1", str(text))


def parse_md_table_rows(md: str) -> tuple[list[str], list[list[str]]]:
    """Return (headers, data_rows) parsed from the first markdown table in md."""
    table_lines = [l.strip() for l in md.split("\n") if l.strip().startswith("|")]
    if len(table_lines) < 3:
        return [], []
    headers = [h.strip() for h in table_lines[0].split("|")[1:-1]]
    rows = []
    for row_line in table_lines[2:]:
        cells = [c.strip() for c in row_line.split("|")[1:-1]]
        if len(cells) >= len(headers):
            rows.append(cells[: len(headers)])
    return headers, rows
