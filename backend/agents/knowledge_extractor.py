"""KnowledgeExtractor — 从单个 chunk 抽取结构化知识点。

设计详见 docs/design/01_knowledge_extraction.md。

关键约束（docs/design 原则映射到代码）：
  - 增量化：按 chunk 缓存，幂等键 = chunk 文本哈希；未变化的 chunk 不重抽。
  - feature flag off 默认：本类不直接判断 flag——调用方（MemoryAgent）判。
  - 失败不抛：抽取失败的 chunk 写 .error.json，不让整批失败。
  - edited_by_user 保留：merge 阶段由 kp_store.merge_kps() 处理。
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Iterable

from backend.agents.base import AgentBase, load_prompt
from backend.core import kp_store
from backend.core.chunker import Chunk
from backend.core import llm as _llm_mod
from backend.core.llm import (
    LLMConfig,
    SchemaValidationError,
    parse_with_schema,
)
from backend.core.project import project_manager
from backend.core.timeutil import utc_iso_z
from backend.schemas.knowledge_point import (
    KnowledgePoint,
    KPExtractItem,
    KPExtractOutput,
    KPSource,
)


logger = logging.getLogger(__name__)


DEFAULT_EXTRACT_SYS = (
    "你是资深测试需求分析专家 / 测试知识图谱构建工程师。"
    "任务：从给定**文档片段**中抽取**原子级、测试导向**的知识点（KP），"
    "输出结构化 JSON，供下游用例生成、需求覆盖度矩阵、变更影响面分析直接消费。\n\n"
    "====================\n"
    "核心原则（强约束）\n"
    "====================\n"
    "1. **原子性**：一条 KP 只承载一条事实（一条规则 / 一个约束 / 一个边界 / 一条异常 / "
    "一条验收 / 一个接口 / 一个字段）；边界必须拆分（min、max 各一条），禁止合并；\n"
    "2. **测试导向**：每条 KP 必须能直接转化为至少 1 条测试用例的断言点；"
    "剔除背景/动机/历史/市场等非测试信息；同等密度下优先抽取**边界与异常**；\n"
    "3. **事实忠诚**：只抽片段中**字面或同义明确出现**的内容；"
    "禁止基于常识补全默认值、单位、错误码、状态码；禁止外推；\n"
    "4. **抽不到就返空**：整段无可抽内容时，直接输出 `{\"items\":[]}`，禁止编造兜底。\n\n"
    "====================\n"
    "type 受限枚举（禁止自造）\n"
    "====================\n"
    "- `business_rule`：业务规则（如『订单 ≥100 元享受满减』）；\n"
    "- `input_constraint`：输入格式/字符集/必填（如『手机号 11 位，以 1 开头』）；\n"
    "- `boundary`：数值/长度/时间/容量边界（如『密码最短 6 位』，min 与 max 各一条）；\n"
    "- `exception_flow`：错误/失败/超时/锁定等异常路径（如『输错 5 次锁定 30 分钟』）；\n"
    "- `acceptance_criteria`：操作后的可观测结果（如『登录成功跳转首页』）；\n"
    "- `api_spec`：接口路径/方法/入参/出参（如『POST /api/login，入参 u/p，返回 token』）；\n"
    "- `data_field`：字段类型/枚举/默认值（如『order.status 枚举 pending/paid/cancelled』）。\n\n"
    "多 type 冲突时归类优先级："
    "`api_spec` > `data_field` > `boundary` > `input_constraint` > "
    "`exception_flow` > `acceptance_criteria` > `business_rule`。\n\n"
    "====================\n"
    "字段规范（全部必填，不得省略键）\n"
    "====================\n"
    "- `type`：string，上述 7 个枚举之一；\n"
    "- `content`：string，陈述句、≤150 字、单一语义、不含问句/标题式措辞；\n"
    "- `module`：string，中文短名（如『登录』、『下单』、『支付』），"
    "须与 memory.md / system.json 的规范模块名**严格一致**；\n"
    "- `aliases`：string[]，片段中出现过的同义称呼，≤5 条；无则 `[]`；\n"
    "- `section`：string | null，从 Markdown 标题/编号抽取（如 `\"3.2\"`、`\"登录校验\"`）；抽不到填 `null`；\n"
    "- `confidence`：number，[0, 1] 两位小数；<0.5 的**不抽取**（宁缺毋滥）。\n\n"
    "置信度分级：\n"
    "- `≥0.9`：原文字面直述；\n"
    "- `0.7~0.9`：语义清晰但需轻微改写为陈述句；\n"
    "- `0.5~0.7`：需从上下文推断主语/模块；\n"
    "- `<0.5`：不抽取。\n\n"
    "====================\n"
    "输出约束\n"
    "====================\n"
    "1. 只输出**一个合法 JSON 对象**，以 `{\"items\":` 开头；\n"
    "2. **禁止**输出 Markdown 代码围栏、解释、前言、结语、思考过程；\n"
    "3. **字段齐全**：每个 item 必须包含全部 6 个字段，不得省略键；\n"
    "4. **JSON 合法性**：UTF-8、双引号、无尾随逗号、布尔/空值小写、数字不带引号；\n"
    "5. `items` 内按在原文出现顺序排列；语义重复的条目合并 `aliases` 后只保留一条；\n"
    "6. 无可抽取内容时输出 `{\"items\":[]}`。\n\n"
    "输出 Schema:\n"
    '{"items": [{"type": str, "content": str, "module": str, '
    '"aliases": [str], "section": str | null, "confidence": float}]}'
)


def _now_iso() -> str:
    return utc_iso_z()


def _chunk_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _build_chunk_id(source: str, index: int, text: str) -> str:
    """与 VectorStore 的 id 规则对齐：source::index::content_hash。

    VectorStore 里是 source::index::global_idx（global_idx 是 FAISS 行号，重建后可能变）。
    为了 KP 的反向定位稳定，这里独立地用 content_hash 拼 chunk_id 存进 KP，
    避免依赖 FAISS 行号变化。
    """
    return f"{source}::{index}::{_chunk_hash(text)}"


class KnowledgeExtractor(AgentBase):
    name = "knowledge_extractor"

    # ---- 对外入口 --------------------------------------------------------

    def extract_for_chunks(
        self,
        chunks: list[Chunk],
        source_file: str,
        doc_version: str,
        llm_cfg: LLMConfig,
    ) -> list[KnowledgePoint]:
        """对一个文档的所有 chunk 抽取 KP（带缓存）。

        返回的是**本次抽取到的 KP**，不包含从缓存里读出的老 KP——调用方自己决定
        要不要和已有 knowledge_points.json 合并。
        """
        results: list[KnowledgePoint] = []
        for ch in chunks:
            try:
                kps = self._extract_one_chunk(
                    ch, source_file=source_file,
                    doc_version=doc_version, llm_cfg=llm_cfg,
                )
                results.extend(kps)
            except Exception as e:
                # 单 chunk 失败不影响其他 chunk
                logger.warning("KP 抽取 chunk 失败 %s[%d]: %s", source_file, ch.index, e)
                self._write_error_cache(
                    source_file, ch, reason=f"unexpected: {e!r}",
                )
        return results

    # ---- 核心：单 chunk 抽取 ---------------------------------------------

    def _extract_one_chunk(
        self,
        chunk: Chunk,
        source_file: str,
        doc_version: str,
        llm_cfg: LLMConfig,
    ) -> list[KnowledgePoint]:
        chunk_id = _build_chunk_id(source_file, chunk.index, chunk.text)
        cpath = kp_store.cache_path(self.project, chunk_id)

        # --- 幂等缓存命中 ---
        if cpath.exists():
            try:
                cached = json.loads(cpath.read_text(encoding="utf-8"))
                return [KnowledgePoint.model_validate(x) for x in cached]
            except Exception:
                # 缓存坏了就重抽
                cpath.unlink(missing_ok=True)

        # --- LLM 抽取 ---
        sys_prompt = load_prompt("extract/knowledge_points.txt") or DEFAULT_EXTRACT_SYS
        user = (
            f"源文件: {source_file}\n"
            f"chunk_index: {chunk.index}\n\n"
            f"===== 文档片段 =====\n{chunk.text}\n===== END =====\n\n"
            f"请抽取。只输出 JSON。"
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ]

        try:
            raw = _llm_mod.chat(messages=messages, cfg=llm_cfg, temperature=0.1, json_mode=True)
        except Exception as e:
            # 网络/鉴权/其他错误——写 error cache，不抛
            self._write_error_cache(source_file, chunk, reason=f"chat error: {e!r}")
            return []

        try:
            parsed: KPExtractOutput = parse_with_schema(
                raw, KPExtractOutput,
                retry_cfg=llm_cfg,
                retry_messages=messages,
                max_retries=1,
            )
        except SchemaValidationError as e:
            self._write_error_cache(
                source_file, chunk,
                reason="schema validation failed",
                raw_output=e.raw_output,
                validation_error=str(e.validation_error),
            )
            return []

        kps = self._assemble(
            parsed.items, source_file=source_file, chunk=chunk,
            chunk_id=chunk_id, doc_version=doc_version,
        )
        # 写缓存
        try:
            cpath.write_text(
                json.dumps([kp.model_dump() for kp in kps], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("KP 缓存写入失败: %s", cpath)
        return kps

    # ---- 组装 KPExtractItem -> KnowledgePoint ---------------------------

    def _assemble(
        self,
        items: list[KPExtractItem],
        source_file: str,
        chunk: Chunk,
        chunk_id: str,
        doc_version: str,
    ) -> list[KnowledgePoint]:
        out: list[KnowledgePoint] = []
        now = _now_iso()
        for item in items:
            kp_id = kp_store.next_kp_id(self.project, item.module, item.type)
            out.append(KnowledgePoint(
                kp_id=kp_id,
                type=item.type,
                content=item.content,
                module=item.module,
                aliases=list(dict.fromkeys([a for a in (item.aliases or []) if a])),
                source=KPSource(
                    file=source_file, chunk_id=chunk_id, section=item.section,
                ),
                doc_version=doc_version,
                confidence=item.confidence,
                extracted_at=now,
                edited_by_user=False,
                orphan=False,
            ))
        return out

    # ---- 出错 cache ------------------------------------------------------

    def _write_error_cache(
        self,
        source_file: str,
        chunk: Chunk,
        *,
        reason: str,
        raw_output: str = "",
        validation_error: str = "",
    ) -> None:
        chunk_id = _build_chunk_id(source_file, chunk.index, chunk.text)
        epath = kp_store.error_cache_path(self.project, chunk_id)
        payload = {
            "source": source_file,
            "chunk_index": chunk.index,
            "reason": reason,
            "raw_output": (raw_output or "")[:4000],
            "validation_error": (validation_error or "")[:2000],
            "at": _now_iso(),
        }
        try:
            epath.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
            )
        except OSError:
            pass

    # ---- 增量入口 -------------------------------------------------------

    def extract_incremental(
        self,
        changed_sources: list[tuple[str, str, list[Chunk]]],
        llm_cfg: LLMConfig,
        live_sources: set[str] | None = None,
    ) -> dict:
        """按变动文件批量抽取，并合并进 knowledge_points.json。

        Parameters
        ----------
        changed_sources : list of (source_file, doc_version, chunks)
            调用方（MemoryAgent）自己选出哪些文件要重抽。
        live_sources : set of str, optional
            仍然存在的 source 文件集合，用于把其他不在此集合中的 KP 标 orphan。

        Returns
        -------
        dict  统计信息
        """
        newly: list[KnowledgePoint] = []
        affected_chunks: set[str] = set()
        for source_file, doc_version, chunks in changed_sources:
            # 先登记本批影响的所有 chunk_id（即便抽取到 0 条也要替换旧 KP）
            for ch in chunks:
                affected_chunks.add(_build_chunk_id(source_file, ch.index, ch.text))
            kps = self.extract_for_chunks(
                chunks, source_file=source_file,
                doc_version=doc_version, llm_cfg=llm_cfg,
            )
            newly.extend(kps)

        existing = kp_store.load_all(self.project)
        merged, stats = kp_store.merge_kps(
            existing, newly,
            affected_chunk_ids=affected_chunks,
            live_sources=live_sources,
        )
        kp_store.save_all(self.project, merged)
        return {
            "project": self.project,
            "added": stats.added,
            "replaced": stats.replaced,
            "preserved_edited": stats.preserved_edited,
            "orphaned": stats.orphaned,
            "total": len(merged),
        }

    def rebuild_all(
        self,
        all_sources: list[tuple[str, str, list[Chunk]]],
        llm_cfg: LLMConfig,
        keep_edited: bool = True,
    ) -> dict:
        """全量重建：清缓存 + seq；可选保留 edited_by_user 的 KP。"""
        edited_backup: list[KnowledgePoint] = []
        if keep_edited:
            edited_backup = [kp for kp in kp_store.load_all(self.project) if kp.edited_by_user]

        kp_store.clear_all(self.project)

        newly: list[KnowledgePoint] = []
        live_sources: set[str] = set()
        for source_file, doc_version, chunks in all_sources:
            live_sources.add(source_file)
            kps = self.extract_for_chunks(
                chunks, source_file=source_file,
                doc_version=doc_version, llm_cfg=llm_cfg,
            )
            newly.extend(kps)

        # edited_backup 里的 orphan 判定
        preserved = []
        for kp in edited_backup:
            if kp.source.file not in live_sources:
                kp = kp.model_copy(update={"orphan": True})
            preserved.append(kp)

        merged = preserved + newly
        kp_store.save_all(self.project, merged)
        return {
            "project": self.project,
            "total": len(merged),
            "newly_extracted": len(newly),
            "preserved_edited": len(preserved),
        }
