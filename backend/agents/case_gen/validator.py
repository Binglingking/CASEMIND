"""Step 4：用例校验（Validator Agent，纯代码，不调 LLM）。

职责（docs/design/03 §5.4）：
  1. **Schema 校验**：逐条用 TestCase.model_validate 过；不合规直接进 invalid_cases。
  2. **可追溯性校验**：source_refs.kp_id 必须在 KP 全量表里；chunk_id 必须在
     VectorStore 的 chunk id 清单里；二者都不存在即"追溯断链"。
  3. **业务规则校验**：
     - case_id 唯一
     - case_id 命名 TC_<module>_<4 位数字>
     - priority/category 枚举（由 pydantic 自动校验，额外给 warning 兜底）
     - 集成用例 related_feature_points 必须 ≥2
     - steps[].data 不能是抽象描述（heuristics：纯"合法/过长/随机"类词语 → warning）
  4. **四类覆盖自检**：正常/异常/边界/安全缺任何一类时 → warnings（不 fail）

失败不抛：收集到 ValidateResult.output（即 ValidateOutput）里。

调用者：CaseGenPipeline.run_step4。不使用 LLM。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from pydantic import ValidationError

from backend.agents.base import AgentBase
from backend.schemas.test_case import InvalidCase, TestCase, ValidateOutput


logger = logging.getLogger(__name__)


# case_id 命名：TC_<module>_<4 位数字>，module 允许中英文数字下划线
_CASE_ID_RE = re.compile(r"^TC_[一-龥A-Za-z0-9_]+_\d{4}$")

# steps[].data 的抽象描述黑名单（覆盖常见模糊表述）
_ABSTRACT_DATA_PATTERNS = [
    re.compile(r"^(合法|有效|正确|正常)(的)?[^\s]*$"),
    re.compile(r"^(非法|无效|错误|异常)(的)?[^\s]*$"),
    re.compile(r"^(过长|超长|过短|很长)[^\s]*$"),
    re.compile(r"^(任意|随机|某个|一些)[^\s]*$"),
    re.compile(r"^(正确格式|正确的格式|错误格式)"),
]

# 必须覆盖的 category 四类（安全/边界缺失通常是接口/表单类 FP 的大问题）
REQUIRED_CATEGORIES = ("正常", "异常", "边界", "安全")


@dataclass
class ValidateResult:
    output: ValidateOutput
    error: Optional[str] = None  # 运行期异常（理论上不应发生）

    @property
    def valid_count(self) -> int:
        return len(self.output.valid_cases)

    @property
    def invalid_count(self) -> int:
        return len(self.output.invalid_cases)


class Validator(AgentBase):
    name = "validator"

    def run(
        self,
        cases: list,                                     # list[TestCase] 或 list[dict]（PR 边界兜底）
        *,
        allowed_kp_ids: set[str],
        allowed_chunk_ids: set[str],
        valid_fp_ids: Optional[set[str]] = None,
    ) -> ValidateResult:
        """对全部 case 做 schema + 追溯 + 业务规则校验。

        Parameters
        ----------
        cases : list
            合并阶段（Step 3）的 merged_cases。可能是 TestCase 实例或 dict（被用户编辑过）。
        allowed_kp_ids : set[str]
            合法 kp_id 集合（通常来自 kp_store.load_all(project)）。
        allowed_chunk_ids : set[str]
            合法 chunk_id 集合（通常来自 VectorStore.all_chunks()）。
        valid_fp_ids : set[str], optional
            可选：集成用例里的 related_feature_points 会用这个做校验。
            None 时跳过该检查。
        """
        valid: list[TestCase] = []
        invalid: list[InvalidCase] = []
        warnings: list[str] = []

        # ---- 第一遍：逐条 schema + 业务规则 ----
        seen_ids: dict[str, int] = {}          # case_id -> valid 列表里的下标
        for idx, raw in enumerate(cases):
            tc, errors = _to_testcase(raw)
            if tc is None:
                invalid.append(InvalidCase(
                    case=_case_dict(raw),
                    errors=errors,
                ))
                continue

            per_case_errors = _validate_business_rules(
                tc,
                allowed_kp_ids=allowed_kp_ids,
                allowed_chunk_ids=allowed_chunk_ids,
                valid_fp_ids=valid_fp_ids,
            )
            if per_case_errors:
                invalid.append(InvalidCase(
                    case=tc.model_dump(),
                    errors=per_case_errors,
                ))
                continue

            # case_id 重复检测（保留第一条，后续视为 invalid）
            if tc.case_id in seen_ids:
                invalid.append(InvalidCase(
                    case=tc.model_dump(),
                    errors=[f"case_id 重复: {tc.case_id} 已存在于下标 {seen_ids[tc.case_id]}"],
                ))
                continue

            # 抽象 data 只给 warning，不踢出
            for w in _data_warnings(tc):
                warnings.append(w)

            seen_ids[tc.case_id] = len(valid)
            valid.append(tc)

        # ---- 第二遍：集合级自检 ----
        warnings.extend(_category_coverage_warnings(valid))

        output = ValidateOutput(
            valid_cases=valid,
            invalid_cases=invalid,
            warnings=warnings,
        )
        return ValidateResult(output=output)


# ============ 帮手函数 =====================================================

def _to_testcase(raw) -> tuple[Optional[TestCase], list[str]]:
    """把原始输入转成 TestCase；失败时返回错误列表。"""
    if isinstance(raw, TestCase):
        return raw, []
    try:
        return TestCase.model_validate(raw), []
    except ValidationError as e:
        return None, [f"{err['loc']}: {err['msg']}" for err in e.errors()]
    except Exception as e:  # noqa: BLE001
        return None, [f"unexpected: {e!r}"]


def _case_dict(raw) -> dict:
    if isinstance(raw, TestCase):
        return raw.model_dump()
    if isinstance(raw, dict):
        return raw
    return {"_raw": repr(raw)}


def _validate_business_rules(
    tc: TestCase,
    *,
    allowed_kp_ids: set[str],
    allowed_chunk_ids: set[str],
    valid_fp_ids: Optional[set[str]],
) -> list[str]:
    errs: list[str] = []

    if not _CASE_ID_RE.match(tc.case_id):
        errs.append(f"case_id 命名不合规，应为 TC_<module>_<4位数字>，实际: {tc.case_id}")

    # source_refs 追溯
    for i, ref in enumerate(tc.source_refs):
        kp_ok = bool(ref.kp_id) and ref.kp_id in allowed_kp_ids
        ch_ok = bool(ref.chunk_id) and ref.chunk_id in allowed_chunk_ids
        if not (kp_ok or ch_ok):
            errs.append(
                f"source_refs[{i}] 追溯断链: kp_id={ref.kp_id} chunk_id={ref.chunk_id}"
            )

    # 集成用例：related_feature_points ≥2
    if tc.generated_by == "merger_agent" or len(tc.related_feature_points) >= 1:
        # related_feature_points 非空时，其成员必须存在；≥1 却不足 2 视为集成未成立
        if tc.related_feature_points:
            if len(set(tc.related_feature_points)) < 2 and tc.generated_by == "merger_agent":
                errs.append("集成用例 related_feature_points 必须 ≥2")
            if valid_fp_ids is not None:
                unknown = set(tc.related_feature_points) - valid_fp_ids
                if unknown:
                    errs.append(f"related_feature_points 含未知 fp_id: {sorted(unknown)}")

    return errs


def _data_warnings(tc: TestCase) -> list[str]:
    out: list[str] = []
    for i, step in enumerate(tc.steps):
        d = (step.data or "").strip()
        if not d:
            continue
        for pat in _ABSTRACT_DATA_PATTERNS:
            if pat.match(d):
                out.append(
                    f"{tc.case_id} steps[{i}].data 疑似抽象描述 '{d}'，应具体到值"
                )
                break
    return out


def _category_coverage_warnings(cases: list[TestCase]) -> list[str]:
    if not cases:
        return []
    seen = {c.category for c in cases}
    missing = [cat for cat in REQUIRED_CATEGORIES if cat not in seen]
    if not missing:
        return []
    return [f"用例集合缺失 category: {'/'.join(missing)}（可能导致覆盖不足）"]
