"""Utilities for converting test cases between dict list and Markdown table format."""
from __future__ import annotations

import re

HEADERS = ["序号", "目录", "模块", "子项", "用例名称", "前置条件", "用例步骤", "预期结果", "优先级", "类型"]
_SPLIT_COLS = {"前置条件", "用例步骤", "预期结果"}


def _esc(s: str) -> str:
    return str(s).replace("|", "｜").replace("\n", " ").strip()


def _normalize_to_numbered(value, *, step_dict_ok: bool = False) -> str:
    """Coerce list/str/dict into numbered `1.x 2.y 3.z` form (space-joined for md table)."""
    if value is None or value == "":
        return ""
    if isinstance(value, list):
        parts = []
        for j, item in enumerate(value):
            if step_dict_ok and isinstance(item, dict):
                text = f"{item.get('action', '')} {item.get('data', '')}".strip()
            else:
                text = str(item).strip()
            if not text:
                continue
            text = re.sub(r"^\s*\d+[\.\)、]\s*", "", text)
            parts.append(f"{j + 1}.{text}")
        return " ".join(parts)
    text = str(value).strip()
    if not text:
        return ""
    if re.search(r"\d+\s*[\.\)、]", text):
        segs = re.split(r"\s*(?:^|\s)(\d+)\s*[\.\)、]\s*", text)
        items: list[str] = []
        if segs and segs[0].strip() == "":
            segs = segs[1:]
        elif segs and not segs[0].strip().isdigit():
            head = segs[0].strip()
            if head:
                items.append(head)
            segs = segs[1:]
        for k in range(0, len(segs), 2):
            body = segs[k + 1].strip() if k + 1 < len(segs) else ""
            if body:
                items.append(body)
        if items:
            return " ".join(f"{i + 1}.{t}" for i, t in enumerate(items))
    lines = [ln.strip() for ln in re.split(r"[\n;；]+", text) if ln.strip()]
    if len(lines) > 1:
        return " ".join(f"{i + 1}.{t}" for i, t in enumerate(lines))
    return f"1.{text}"


def cases_to_md(cases: list[dict], title: str = "测试用例") -> str:
    lines = [f"# {title}\n"]
    lines.append("| " + " | ".join(HEADERS) + " |")
    lines.append("| " + " | ".join(["---"] * len(HEADERS)) + " |")

    for i, c in enumerate(cases, 1):
        step_text = _normalize_to_numbered(c.get("steps", []), step_dict_ok=True)
        pre_text = _normalize_to_numbered(c.get("preconditions", ""))
        expected_text = _normalize_to_numbered(
            c.get("expected_result") or c.get("expected", "")
        )

        row = [
            str(i),
            c.get("catalog", ""),
            c.get("module", ""),
            c.get("sub_item", ""),
            c.get("name") or c.get("title", ""),
            pre_text,
            step_text,
            expected_text,
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

        def _split_to_list(s: str) -> list[str]:
            return [t.strip() for t in re.split(r"(?:^|\s+)\d+\.", s) if t.strip()]

        steps = _split_to_list(rd.get("用例步骤", ""))
        pre_list = _split_to_list(rd.get("前置条件", ""))
        expected_list = _split_to_list(rd.get("预期结果", ""))

        cases.append({
            "catalog": rd.get("目录", ""),
            "module": rd.get("模块", ""),
            "sub_item": rd.get("子项", ""),
            "name": rd.get("用例名称", ""),
            "title": rd.get("用例名称", ""),
            "preconditions": pre_list or rd.get("前置条件", ""),
            "steps": steps,
            "expected": expected_list or rd.get("预期结果", ""),
            "expected_result": expected_list or rd.get("预期结果", ""),
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


def format_numbered_multiline(value) -> str:
    """Coerce list/str into '1. xxx\\n2. yyy' form for Excel pre/expected cells.

    - list → each item gets `i+1. ` prefix (existing leading numbering stripped)
    - str with embedded `1. ... 2. ...` → renumber, one per line
    - str with newline/`；;` separators → renumber, one per line
    - single-line str → returns as-is (no `1.` prefix for single items)
    """
    if value is None or value == "":
        return ""
    if isinstance(value, list):
        items: list[str] = []
        for v in value:
            if isinstance(v, dict):
                text = str(v.get("text") or v.get("desc") or v).strip()
            else:
                text = str(v).strip()
            if not text:
                continue
            text = re.sub(r"^\s*\d+[\.\)、]\s*", "", text)
            items.append(text)
        if not items:
            return ""
        if len(items) == 1:
            return items[0]
        return "\n".join(f"{i + 1}. {t}" for i, t in enumerate(items))
    text = str(value).strip()
    if not text:
        return ""
    # Embedded numbering like "1. xxx 2. yyy" → split & renumber
    if re.search(r"(?:^|\s)\d+\s*[\.\)、]", text):
        segs = re.split(r"\s*(?:^|\s)(\d+)\s*[\.\)、]\s*", text)
        items = []
        if segs and segs[0].strip() == "":
            segs = segs[1:]
        elif segs and not segs[0].strip().isdigit():
            head = segs[0].strip()
            if head:
                items.append(head)
            segs = segs[1:]
        for k in range(0, len(segs), 2):
            body = segs[k + 1].strip() if k + 1 < len(segs) else ""
            if body:
                items.append(body)
        if len(items) > 1:
            return "\n".join(f"{i + 1}. {t}" for i, t in enumerate(items))
        if items:
            return items[0]
    # Newline / `；;` separators
    lines = [ln.strip() for ln in re.split(r"[\n;；]+", text) if ln.strip()]
    if len(lines) > 1:
        return "\n".join(f"{i + 1}. {t}" for i, t in enumerate(lines))
    return text


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
