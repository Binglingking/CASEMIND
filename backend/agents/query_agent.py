"""QueryAgent — RAG using memory_prompt.txt + vector retrieval."""
from __future__ import annotations

import base64
import json
from pathlib import Path

from backend.agents.base import AgentBase, load_prompt
from backend.config import Features, settings
from backend.core.hybrid_retriever import HybridRetriever
from backend.core.llm import LLMConfig, chat, chat_stream, try_parse_json
from backend.core.project import project_manager
from backend.core.timeutil import utc_compact
from backend.core.vector_store import VectorStore


def _read_features() -> Features:
    """运行时读取磁盘上的 features.json；文件缺失/损坏时返回 settings.features 默认。

    把 import 放在函数内是为了避免 app 启动时的循环 import（routes_settings 会反向
    引用 backend.services 里的东西）。
    """
    try:
        from backend.api.routes_settings import get_runtime_features
        return get_runtime_features()
    except Exception:
        return settings.features


QueryMode = str  # "qa" | "chat" | "testcase" | "xmind" | "req_analysis"

# keep at most this many prior turns in the prompt to cap tokens
MAX_HISTORY_TURNS = 12
MAX_HISTORY_CHARS = 12000


def _memory_prompt(project: str) -> str:
    p = project_manager.mem_dir(project) / "memory_prompt.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _compact_history(history: list[dict]) -> list[dict]:
    if not history:
        return []
    clean = []
    for m in history:
        role = (m.get("role") or "").strip().lower()
        content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        clean.append({"role": role, "content": content})
    if len(clean) > MAX_HISTORY_TURNS:
        clean = clean[-MAX_HISTORY_TURNS:]
    # char budget (truncate oldest first)
    total = sum(len(m["content"]) for m in clean)
    while total > MAX_HISTORY_CHARS and len(clean) > 2:
        dropped = clean.pop(0)
        total -= len(dropped["content"])
    return clean


def _format_references(blocks: list[dict]) -> str:
    if not blocks:
        return ""
    parts = [
        "以下是用户通过 @ 引用的文件内容。"
        "生成用例 / XMind / 答案时，请结合这些内容进行分析和回答，"
        "但不要原样抄袭；事实仍以系统记忆 + 检索片段为准。",
    ]
    for i, b in enumerate(blocks, 1):
        trunc = "（已截断）" if b.get("truncated") else ""
        parts.append(f"\n--- 引用文件 {i} · @{b.get('label') or b.get('name')}{trunc} ---")
        parts.append(b.get("content") or "")
    return "\n".join(parts).strip()


def _save_req_analysis_outputs(project: str, data: dict, ts: str) -> dict:
    out_dir = project_manager.out_req_analysis_dir(project)
    json_path = out_dir / f"req_analysis_{ts}.json"
    pdf_path = out_dir / f"req_analysis_{ts}.pdf"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    from backend.services.req_analysis_service import generate_pdf_report
    pdf_path.write_bytes(generate_pdf_report(project, data))

    return {
        "output_file": str(json_path),
        "output_filename": json_path.name,
        "pdf_file": str(pdf_path),
        "pdf_filename": pdf_path.name,
    }


class QueryAgent(AgentBase):
    name = "query"

    def run(self, question: str, mode: QueryMode, llm_cfg: LLMConfig,
            top_k: int | None = None,
            history: list[dict] | None = None,
            reference_blocks: list[dict] | None = None,
            images: list[str] | None = None,
            stream_callback=None) -> dict:
        """stream_callback(event_type, text) 用于实时推送"""
        hist = _compact_history(history or [])
        ref_text = _format_references(reference_blocks or [])
        image_urls = images or []

        if stream_callback:
            return self._run_stream(
                question, mode, llm_cfg, top_k, hist, ref_text, image_urls,
                stream_callback,
            )

        if mode == "chat":
            return self._chat(question, llm_cfg, hist, ref_text, image_urls)

        if mode == "req_analysis":
            return self._requirement_analysis(question, llm_cfg, hist, ref_text, image_urls)

        top_k = top_k or settings.top_k
        retrieved = self._retrieve(question, top_k)

        ctx = "\n\n".join(
            f"[{c.source} #{c.index}] (score={s:.3f})\n{c.text}"
            for c, s in retrieved
        ) or "(无检索结果)"
        memory_prompt = _memory_prompt(self.project)

        if mode == "testcase":
            return self._testcase(question, ctx, memory_prompt, retrieved, llm_cfg, hist, ref_text, image_urls)
        if mode == "xmind":
            return self._xmind(question, ctx, memory_prompt, retrieved, llm_cfg, hist, ref_text, image_urls)
        return self._qa(question, ctx, memory_prompt, retrieved, llm_cfg, hist, ref_text, image_urls)

    # --- retrieval -------------------------------------------------------

    def _retrieve(self, question: str, top_k: int) -> list[tuple]:
        """按 feature flag 选择检索路径；输出统一为 [(StoredChunk, score)]。

        - flag on：HybridRetriever(namespace="chunks", mode="hybrid")，失败降级到向量检索
        - flag off：原 VectorStore.search 路径，保持 100% 行为兼容

        flags 从 `get_runtime_features()` 读（磁盘 features.json），以便 UI 的
        /api/settings/features PUT 立即生效；不依赖 `settings.features` 的进程内状态。
        """
        feats = _read_features()
        if feats.enable_hybrid_retrieval:
            try:
                results = HybridRetriever(self.project).search(
                    question, top_k=top_k, namespace="chunks", mode="hybrid",
                    use_reranker=bool(feats.enable_reranker),
                )
                return [(r.chunk, r.score) for r in results]
            except Exception:
                # hybrid 内部异常不让查询整体失败，退回纯向量
                pass
        return VectorStore(self.project).search(question, top_k=top_k)

    # --- streaming -------------------------------------------------------

    def _run_stream(self, question, mode, llm_cfg, top_k, hist,
                    ref_text, image_urls, callback):
        """流式运行：检索后逐 chunk 推送给前端。"""
        # chat 模式：无需检索，直接流式回答
        if mode == "chat":
            sys_prompt = (
                "你是通用对话助手。直接根据用户问题进行回答，"
                "不要使用项目需求文档、系统记忆或检索结果，"
                "也不要在回答中标注任何 `[文件名 #序号]` 引用。"
                "如果用户提供了图片，请结合图片内容进行分析回答。"
            )
            msgs = self._build_messages(sys_prompt, question, hist, ref_text, image_urls)
            answer_text = ""
            for evt, text in chat_stream(msgs, llm_cfg, temperature=0.5):
                if evt == 'error':
                    callback('error', text)
                    return {"mode": mode, "answer": answer_text, "sources": []}
                if evt == 'done':
                    return {"mode": mode, "answer": answer_text, "sources": []}
                if evt == 'thinking':
                    callback('thinking', text)
                    continue
                if evt == 'answer':
                    answer_text += text
                    callback('answer', text)
                    continue
            return {"mode": mode, "answer": answer_text, "sources": []}

        # req_analysis 模式：流式后解析 JSON
        if mode == "req_analysis":
            sys_prompt = DEFAULT_REQ_ANALYSIS
            user = (
                f"请对以下需求文档进行全面的质量分析：\n\n"
                f"===== 需求文档内容 =====\n{question}\n"
                f"===== END =====\n\n"
            )
            if ref_text:
                user += f"===== 引用文件补充 =====\n{ref_text}\n===== END =====\n\n"
            user += "请严格按 JSON 格式输出分析结果，不要 Markdown 围栏、不要前言结语。"
            if image_urls:
                user += "\n\n注意：需求文档中可能包含截图/图片，请结合图片内容进行分析。"

            msgs = self._build_messages(sys_prompt, user, hist, "", image_urls)
            answer_text = ""
            for evt, text in chat_stream(msgs, llm_cfg, temperature=0.15, json_mode=True):
                if evt == 'error':
                    callback('error', text)
                    return {"mode": mode, "answer": answer_text, "sources": []}
                if evt == 'done':
                    data = try_parse_json(answer_text) or {
                        "issues": [], "statistics": {}, "summary": "", "_raw": answer_text,
                    }
                    ts = utc_compact()
                    files = _save_req_analysis_outputs(self.project, data, ts)
                    return {
                        "mode": mode,
                        "answer": answer_text,
                        "data": data,
                        "sources": [],
                        **files,
                    }
                if evt == 'thinking':
                    callback('thinking', text)
                    continue
                if evt == 'answer':
                    answer_text += text
                    callback('answer', text)
                    continue
            return {"mode": mode, "answer": answer_text, "sources": []}

        # qa / testcase / xmind 模式：先检索，再流式回答
        if mode in ("qa", "testcase", "xmind"):
            top_k = top_k or settings.top_k
            retrieved = self._retrieve(question, top_k)
            ctx = "\n\n".join(
                f"[{c.source} #{c.index}] (score={s:.3f})\n{c.text}"
                for c, s in retrieved
            ) or "(无检索结果)"
            memory_prompt = _memory_prompt(self.project)

            # 按模式选择 prompt 和参数
            if mode == "qa":
                base = load_prompt("query.txt") or (
                    "你是需求分析助手。\n"
                    "信息源优先级（严格遵守）：\n"
                    "  1. 用户本轮问题\n"
                    "  2. 『PRIMARY SOURCES（检索原文）』——具体细节的**唯一**来源\n"
                    "  3. 『SYSTEM INDEX（memory.md）』——仅用于项目全貌导航\n"
                    "细节、字段、数值、步骤、措辞必须出自 PRIMARY SOURCES；"
                    "若 PRIMARY SOURCES 不足，如实说明缺失，并从 INDEX 中指出最可能相关的文档建议用户追加。"
                    "每条结论后必须标注来源 `[文件名 #序号]`。"
                )
                sys_prompt = (memory_prompt + "\n\n" + base).strip() if memory_prompt else base
                user = (
                    f"问题: {question}\n\n"
                    f"===== PRIMARY SOURCES（权威原文，事实依据）=====\n{ctx}\n"
                    f"===== END PRIMARY SOURCES =====\n\n"
                    f"请按规则作答，并在结论末尾标注 [文件名 #序号]。"
                )
                json_mode = False
            elif mode == "testcase":
                base = load_prompt("testcase.txt") or DEFAULT_TESTCASE
                sys_prompt = (memory_prompt + "\n\n" + base).strip() if memory_prompt else base
                user = (
                    f"需求描述/目标: {question}\n\n"
                    f"===== PRIMARY SOURCES（权威原文，用例依据）=====\n{ctx}\n"
                    f"===== END PRIMARY SOURCES =====\n\n"
                    f"规则：用例的需求点、字段、步骤、预期必须来自 PRIMARY SOURCES；"
                    f"SYSTEM INDEX 只用于全局定位，不得作为唯一依据。"
                    f"若 PRIMARY SOURCES 未覆盖某功能点，设置 uncertain=true 并在 source_refs 中留空或标注『缺失』。"
                    f"请严格按 JSON 格式输出测试用例。"
                )
                json_mode = True
            else:  # xmind
                base = load_prompt("xmind.txt") or DEFAULT_XMIND
                sys_prompt = (memory_prompt + "\n\n" + base).strip() if memory_prompt else base
                user = (
                    f"主题: {question}\n\n"
                    f"===== PRIMARY SOURCES（权威原文，思维导图节点依据）=====\n{ctx}\n"
                    f"===== END PRIMARY SOURCES =====\n\n"
                    f"规则：思维导图节点内容必须来自 PRIMARY SOURCES；SYSTEM INDEX 仅用于定位方向，"
                    f"不作为节点事实依据。推测节点末尾加 (?) 。\n"
                    f"请输出可导入 XMind 的 Markdown 层级结构。"
                )
                json_mode = False

            if image_urls:
                user += "\n\n注意：用户在此问题中附带了图片，请结合图片内容进行分析。"

            msgs = self._build_messages(sys_prompt, user, hist, ref_text, image_urls)
            answer_text = ""
            for evt, text in chat_stream(msgs, llm_cfg,
                                         temperature=0.2, json_mode=json_mode):
                if evt == 'error':
                    callback('error', text)
                    return {"mode": mode, "answer": answer_text, "sources": []}
                if evt == 'done':
                    sources = [
                        {"source": c.source, "index": c.index, "score": s, "text": c.text}
                        for c, s in retrieved
                    ]
                    result: dict = {"mode": mode, "answer": answer_text, "sources": sources}

                    # 保存 testcase / xmind 输出文件
                    ts = utc_compact()
                    if mode == "testcase":
                        data = try_parse_json(answer_text) or {"cases": [], "_raw": answer_text}
                        if isinstance(data, list):
                            data = {"cases": data}
                        data.setdefault("cases", [])
                        from backend.services.md_case_utils import cases_to_md
                        md_content = cases_to_md(data.get("cases", []), title=f"测试用例_{ts}")
                        out = project_manager.out_testcase_dir(self.project) / f"testcase_{ts}.md"
                        out.write_text(md_content, encoding="utf-8")
                        result["data"] = data
                        result["output_file"] = str(out)
                        try:
                            from backend.api.routes_settings import get_runtime_features
                            if get_runtime_features().enable_case_gen_pipeline:
                                result["pipeline_mode_available"] = True
                                result["pipeline_hint"] = (
                                    "enable_case_gen_pipeline 已开启；建议使用 POST /api/case-gen/start "
                                    "走 Slicer→Generator→Merger→Validator 4 步流水线以获取更高覆盖率。"
                                )
                        except Exception:
                            pass
                    elif mode == "xmind":
                        out = project_manager.out_xmind_dir(self.project) / f"xmind_{ts}.md"
                        out.write_text(answer_text, encoding="utf-8")
                        result["markdown"] = answer_text
                        result["output_file"] = str(out)

                    return result
                if evt == 'thinking':
                    callback('thinking', text)
                    continue
                if evt == 'answer':
                    answer_text += text
                    callback('answer', text)
                    continue
            return {"mode": mode, "answer": answer_text, "sources": []}

    # --- modes -----------------------------------------------------------

    def _image_dir(self) -> Path:
        return project_manager.mem_dir(self.project) / "images"

    def _load_images_as_base64(self, image_urls: list[str]) -> list[dict]:
        """Load images from disk and return as base64 content parts for vision models."""
        parts = []
        for url in image_urls:
            # url格式: /api/images/<project>/<filename>
            filename = Path(url).name
            img_path = self._image_dir() / filename
            if not img_path.exists():
                continue
            try:
                data = img_path.read_bytes()
                b64 = base64.b64encode(data).decode("ascii")
                # 推断 MIME 类型
                suffix = img_path.suffix.lower()
                mime_map = {
                    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".gif": "image/gif", ".webp": "image/webp",
                }
                mime = mime_map.get(suffix, "image/png")
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                })
            except Exception:
                continue
        return parts

    def _build_messages(self, sys_prompt: str, user: str, hist: list[dict],
                        ref_text: str = "", image_urls: list[str] | None = None) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": sys_prompt}]
        if ref_text:
            msgs.append({"role": "system", "content": ref_text})
        msgs.extend(hist)
        # 构建用户消息，支持图片
        urls = image_urls or []
        if urls:
            image_parts = self._load_images_as_base64(urls)
            if image_parts:
                content_parts: list[dict] = [{"type": "text", "text": user}]
                content_parts.extend(image_parts)
                msgs.append({"role": "user", "content": content_parts})
            else:
                msgs.append({"role": "user", "content": user})
        else:
            msgs.append({"role": "user", "content": user})
        return msgs

    def _chat(self, q, llm_cfg, hist, ref_text="", image_urls=None):
        sys_prompt = (
            "你是通用对话助手。直接根据用户问题进行回答，"
            "不要使用项目需求文档、系统记忆或检索结果，也不要在回答中标注任何 `[文件名 #序号]` 引用。"
            "如果用户请求的信息超出你的知识范围，请如实说明。"
            "如果用户提供了图片，请结合图片内容进行分析回答。"
        )
        raw = chat(
            messages=self._build_messages(sys_prompt, q, hist, ref_text, image_urls),
            cfg=llm_cfg, temperature=0.5,
        )
        return {
            "mode": "chat",
            "answer": raw,
            "sources": [],
        }

    def _qa(self, q, ctx, memory_prompt, retrieved, llm_cfg, hist, ref_text="", image_urls=None):
        base = load_prompt("query.txt") or (
            "你是需求分析助手。\n"
            "信息源优先级（严格遵守）：\n"
            "  1. 用户本轮问题\n"
            "  2. 『PRIMARY SOURCES（检索原文）』——具体细节的**唯一**来源\n"
            "  3. 『SYSTEM INDEX（memory.md）』——仅用于项目全貌导航\n"
            "细节、字段、数值、步骤、措辞必须出自 PRIMARY SOURCES；"
            "若 PRIMARY SOURCES 不足，如实说明缺失，并从 INDEX 中指出最可能相关的文档建议用户追加。"
            "每条结论后必须标注来源 `[文件名 #序号]`。"
        )
        sys_prompt = (memory_prompt + "\n\n" + base).strip() if memory_prompt else base
        user = (
            f"问题: {q}\n\n"
            f"===== PRIMARY SOURCES（权威原文，事实依据）=====\n{ctx}\n"
            f"===== END PRIMARY SOURCES =====\n\n"
            f"请按规则作答，并在结论末尾标注 [文件名 #序号]。"
        )
        # 如果有图片，在提示中说明
        if image_urls:
            user += "\n\n注意：用户在此问题中附带了图片，请结合图片内容进行分析。"
        raw = chat(
            messages=self._build_messages(sys_prompt, user, hist, ref_text, image_urls),
            cfg=llm_cfg, temperature=0.2,
        )
        return {
            "mode": "qa",
            "answer": raw,
            "sources": [{"source": c.source, "index": c.index, "score": s,
                         "text": c.text}
                        for c, s in retrieved],
        }

    def _testcase(self, q, ctx, memory_prompt, retrieved, llm_cfg, hist, ref_text="", image_urls=None):
        base = load_prompt("testcase.txt") or DEFAULT_TESTCASE
        sys_prompt = (memory_prompt + "\n\n" + base).strip() if memory_prompt else base
        user = (
            f"需求描述/目标: {q}\n\n"
            f"===== PRIMARY SOURCES（权威原文，用例依据）=====\n{ctx}\n"
            f"===== END PRIMARY SOURCES =====\n\n"
            f"规则：用例的需求点、字段、步骤、预期必须来自 PRIMARY SOURCES；"
            f"SYSTEM INDEX 只用于全局定位，不得作为唯一依据。"
            f"若 PRIMARY SOURCES 未覆盖某功能点，设置 uncertain=true 并在 source_refs 中留空或标注『缺失』。"
            f"请严格按 JSON 格式输出测试用例。"
        )
        if image_urls:
            user += "\n\n注意：用户在此需求描述中附带了一些图片，请结合图片内容设计测试用例。"
        raw = chat(
            messages=self._build_messages(sys_prompt, user, hist, ref_text, image_urls),
            cfg=llm_cfg, temperature=0.2, json_mode=True,
        )
        data = try_parse_json(raw) or {"cases": [], "_raw": raw}
        if isinstance(data, list):
            data = {"cases": data}
        data.setdefault("cases", [])

        ts = utc_compact()
        from backend.services.md_case_utils import cases_to_md
        md_content = cases_to_md(data.get("cases", []), title=f"测试用例_{ts}")
        out = project_manager.out_testcase_dir(self.project) / f"testcase_{ts}.md"
        out.write_text(md_content, encoding="utf-8")

        # 当新流水线启用时，给 UI 一条提示（不改变旧流程）。
        # 真正的 4-步流水线由 /api/case-gen/* 承担；这里保持原功能以兼容老前端。
        try:
            from backend.api.routes_settings import get_runtime_features
            pipeline_enabled = get_runtime_features().enable_case_gen_pipeline
        except Exception:
            pipeline_enabled = False

        resp = {
            "mode": "testcase",
            "data": data,
            "output_file": str(out),
            "sources": [{"source": c.source, "index": c.index, "score": s,
                         "text": c.text}
                        for c, s in retrieved],
        }
        if pipeline_enabled:
            resp["pipeline_mode_available"] = True
            resp["pipeline_hint"] = (
                "enable_case_gen_pipeline 已开启；建议使用 POST /api/case-gen/start "
                "走 Slicer→Generator→Merger→Validator 4 步流水线以获取更高覆盖率。"
            )
        return resp

    def _xmind(self, q, ctx, memory_prompt, retrieved, llm_cfg, hist, ref_text="", image_urls=None):
        base = load_prompt("xmind.txt") or DEFAULT_XMIND
        sys_prompt = (memory_prompt + "\n\n" + base).strip() if memory_prompt else base
        user = (
            f"主题: {q}\n\n"
            f"===== PRIMARY SOURCES（权威原文，思维导图节点依据）=====\n{ctx}\n"
            f"===== END PRIMARY SOURCES =====\n\n"
            f"规则：思维导图节点内容必须来自 PRIMARY SOURCES；SYSTEM INDEX 仅用于定位方向，"
            f"不作为节点事实依据。推测节点末尾加 (?) 。\n"
            f"请输出可导入 XMind 的 Markdown 层级结构。"
        )
        if image_urls:
            user += "\n\n注意：用户在此主题中附带了一些图片，请结合图片内容生成思维导图。"
        raw = chat(
            messages=self._build_messages(sys_prompt, user, hist, ref_text, image_urls),
            cfg=llm_cfg, temperature=0.2,
        )
        ts = utc_compact()
        out = project_manager.out_xmind_dir(self.project) / f"xmind_{ts}.md"
        out.write_text(raw, encoding="utf-8")
        return {
            "mode": "xmind",
            "markdown": raw,
            "output_file": str(out),
            "sources": [{"source": c.source, "index": c.index, "score": s,
                         "text": c.text}
                        for c, s in retrieved],
        }

    def _requirement_analysis(self, q, llm_cfg, hist, ref_text="", image_urls=None):
        """需求分析模式：对产品需求文档进行质量审查。"""
        sys_prompt = DEFAULT_REQ_ANALYSIS
        user = (
            f"请对以下需求文档进行全面的质量分析：\n\n"
            f"===== 需求文档内容 =====\n{q}\n"
            f"===== END =====\n\n"
        )
        if ref_text:
            user += f"===== 引用文件补充 =====\n{ref_text}\n===== END =====\n\n"
        user += "请严格按 JSON 格式输出分析结果，不要 Markdown 围栏、不要前言结语。"
        if image_urls:
            user += "\n\n注意：需求文档中可能包含截图/图片，请结合图片内容进行分析。"

        raw = chat(
            messages=self._build_messages(sys_prompt, user, hist, "", image_urls),
            cfg=llm_cfg, temperature=0.15, json_mode=True,
        )
        data = try_parse_json(raw) or {"issues": [], "statistics": {}, "summary": "", "_raw": raw}

        # 保存分析结果到 outputs 目录
        ts = utc_compact()
        files = _save_req_analysis_outputs(self.project, data, ts)

        return {
            "mode": "req_analysis",
            "data": data,
            "sources": [],
            **files,
        }


DEFAULT_TESTCASE = (
    "你是资深测试用例设计专家。任务：基于**系统记忆（memory.md）**与**检索片段（PRIMARY SOURCES）**"
    "设计结构化测试用例，供测试管理平台（如 TestRail / Zentao / 禅道）直接导入与执行。\n\n"
    "====================\n"
    "知识源优先级（强约束）\n"
    "====================\n"
    "1. **事实依据**：所有用例的 `preconditions`、`steps`、`expected` 必须来自**检索片段**的原文事实；\n"
    "2. **定位辅助**：memory.md 仅用于确定 `catalog`、`module`、`sub_item` 归属与模块间关系，"
    "**不得作为细节（字段、数值、规则）的依据**；\n"
    "3. **冲突以检索片段为准**；\n"
    "4. **无依据不产出**：某个设想用例找不到片段支撑时，**不得编造**——"
    "要么丢弃，要么保留并设置 `uncertain=true` 并在 `name` 末尾标 `(推测)`。\n\n"
    "====================\n"
    "覆盖原则（测试导向）\n"
    "====================\n"
    "1. **正向 + 反向 + 边界 + 异常** 四类至少覆盖其三；\n"
    "2. **边界值**：每个数值/长度/时间约束至少产出 min、min-1、max、max+1 四条边界用例；\n"
    "3. **等价类**：每个输入约束至少一条有效等价类 + 一条无效等价类；\n"
    "4. **异常路径**：片段中出现的每条异常/错误/锁定/超时规则，至少产出一条对应用例；\n"
    "5. **原子性**：一条用例只验证一个断言点；禁止把多个校验塞进一条 `expected`。\n\n"
    "====================\n"
    "字段规范\n"
    "====================\n"
    "- `catalog`：一级分类（如 `功能测试` / `接口测试` / `异常测试` / `安全测试` / `兼容性测试`）；\n"
    "- `module`：业务模块（与 memory.md / system.json 的规范模块名**严格一致**，如『登录』、『下单』）；\n"
    "- `sub_item`：模块下的子功能点（如『密码校验』、『验证码』）；\n"
    "- `name`：用例标题，格式建议 `[正向|反向|边界|异常] 场景描述`，≤50 字；\n"
    "- `preconditions`：前置条件（账号状态、数据准备、环境配置），无前置写 `无`；\n"
    "- `steps`：操作步骤数组，每条一个动作，动词开头（如 `输入手机号 138xxxx0000`），≥1 条；\n"
    "- `expected`：预期结果，**单一断言**、可观测、含具体值/文案/状态码；\n"
    "- `priority`：`P0`（核心主流程/阻塞）/ `P1`（重要分支）/ `P2`（次要/边界）/ `P3`（兜底）；\n"
    "- `type`：`functional` / `boundary` / `negative` / `exception` / `api` / `security` / `compatibility`；\n"
    "- `source_refs`：字符串数组，每条为 `[文件名 #序号]` 字面形式，**至少 1 条**，"
    "对应支撑本用例的检索片段；`uncertain=true` 时允许为空数组；\n"
    "- `uncertain`：布尔；当用例为跨片段推断、片段表述含糊、或无法定位 `source_refs` 时设为 `true`。\n\n"
    "====================\n"
    "输出约束\n"
    "====================\n"
    "1. 只输出**一个合法 JSON 对象**，以 `{\"cases\":` 开头、以 `]}` 结尾；\n"
    "2. **禁止**输出 Markdown 代码围栏、解释、前言、结语、思考过程；\n"
    "3. **字段齐全**：每条用例必须包含全部 10 个字段，无内容用 `\"\"` 或 `[]`，不得省略键；\n"
    "4. **JSON 合法性**：UTF-8、双引号、无尾随逗号、布尔小写；\n"
    "5. 无可设计用例时，输出 `{\"cases\":[]}`，不得编造兜底用例。\n\n"
    "输出 Schema:\n"
    '{"cases": [{"catalog": str, "module": str, "sub_item": str, '
    '"name": str, "preconditions": str, "steps": [str], "expected": str, '
    '"priority": str, "type": str, "source_refs": [str], "uncertain": bool}]}'
)

DEFAULT_XMIND = (
    "你是资深 XMind 结构设计师。任务：基于系统记忆与检索片段，"
    "输出一份可直接导入 XMind 的**纯 Markdown 层级大纲**，用于测试用例脑图、功能结构图或需求分解图。\n\n"
    "====================\n"
    "核心原则（强约束）\n"
    "====================\n"
    "1. **严格基于原文**：只生成片段中明确出现的节点；不得基于常识补全、不得跨系统类比；\n"
    "2. **推测显性化**：跨片段推断、含糊表述的节点，**末尾加 `(?)`**，而非丢弃；\n"
    "3. **层级合理**：同级节点保持**同一抽象粒度**（如同级要么全是模块、要么全是功能点）；\n"
    "4. **原子叶子**：叶子节点表达单一事实/用例/字段，便于 XMind 落盘后直接执行或评审；\n"
    "5. **同义合并**：同义节点（如『登录』与『用户认证』）合并为一个，别名写作 `登录 (别名: 用户认证)`。\n\n"
    "====================\n"
    "Markdown 语法约定\n"
    "====================\n"
    "- **第一行必须是** `# 主题`（根节点，整篇仅一个 `#`）；\n"
    "- `##` = 二级主题（一级分支）；\n"
    "- `###` = 三级主题；\n"
    "- `####` 及以下按需，但**建议总层级 ≤ 5 层**，避免脑图过深；\n"
    "- `-` 列表项 = 叶子节点或更细的子分支；`-` 可嵌套缩进（2 空格）表达多层叶子；\n"
    "- **禁止混用** `*` / `+` 作为列表符号，统一用 `-`；\n"
    "- **禁止使用**表格、代码块、引用块、图片语法——XMind 导入时会丢失或报错。\n\n"
    "====================\n"
    "内容建议\n"
    "====================\n"
    "- 根节点 `# 主题` 取项目名或本次脑图的主题（如 `# 登录模块测试脑图`）；\n"
    "- 二级分支建议按 `功能点 / 异常场景 / 边界 / 接口 / 数据` 等维度组织；\n"
    "- 叶子节点短句化（≤30 字），一个节点一个断言点或一个子功能；\n"
    "- 推测节点示例：`- 验证码有效期 5 分钟 (?)`；\n"
    "- 同义合并示例：`## 登录 (别名: 用户认证)`。\n\n"
    "====================\n"
    "输出约束\n"
    "====================\n"
    "1. 只输出**纯 Markdown 正文**，第一行为 `# 主题`；\n"
    "2. **禁止**输出代码围栏包裹整篇、解释文字、前言结语；\n"
    "3. **禁止**编造原文未出现的节点；推测节点必须以 `(?)` 结尾；\n"
    "4. 若无可生成内容，输出单行 `# （无可生成的脑图内容）`。"
)

DEFAULT_REQ_ANALYSIS = (
    "你是资深产品需求质量审查专家。你的任务是对产品需求文档(PRD)进行全面、深入的质量分析，"
    "帮助测试团队在需求评审阶段发现潜在问题。\n\n"
    "====================\n"
    "分析维度（必须全部覆盖）\n"
    "====================\n"
    "1. **矛盾冲突**：需求中前后不一致、相互矛盾的地方（如两处对同一字段的规则描述不同）；\n"
    "2. **遗漏缺失**：缺少关键信息（如缺少异常处理说明、缺少边界值定义、缺少权限描述、缺少字段类型定义）；\n"
    "3. **逻辑漏洞**：业务流程中的逻辑缺陷（如状态机缺少某些转移、条件判断不完备、循环依赖）；\n"
    "4. **风险识别**：潜在的技术风险、用户体验风险、安全风险、性能风险；\n"
    "5. **歧义模糊**：表述不清、可做多种理解的描述（如『适当』『合理』『必要时』等模糊词）；\n"
    "6. **建议改进**：针对发现的问题给出具体、可操作的改进建议。\n\n"
    "====================\n"
    "严重程度定义\n"
    "====================\n"
    "- **high（高）**：核心功能逻辑矛盾、关键字段缺失、会导致阻塞性Bug或返工的问题；\n"
    "- **medium（中）**：非核心功能缺失、边界条件不清晰、影响测试用例设计的问题；\n"
    "- **low（低）**：文案不统一、格式问题、可优化但非必须的改进建议。\n\n"
    "====================\n"
    "输出格式（严格 JSON）\n"
    "====================\n"
    '{\n'
    '  "summary": "总体评价（2-5句话，概括文档质量、主要发现、建议优先级）",\n'
    '  "statistics": {\n'
    '    "high": 0,\n'
    '    "medium": 0,\n'
    '    "low": 0,\n'
    '    "total": 0\n'
    '  },\n'
    '  "issues": [\n'
    '    {\n'
    '      "id": "ISS-001",\n'
    '      "type": "conflict|omission|logic_flaw|risk|ambiguity|suggestion",\n'
    '      "severity": "high|medium|low",\n'
    '      "title": "简短的问题标题（≤30字）",\n'
    '      "description": "问题的详细描述，引用原文具体段落或相关上下文",\n'
    '      "location": "问题在需求文档中的位置或相关章节",\n'
    '      "impact": "该问题可能导致的后果",\n'
    '      "suggestion": "具体的改进建议（建议项类型可省略此字段）"\n'
    '    }\n'
    '  ]\n'
    '}\n\n'
    "====================\n"
    "输出约束\n"
    "====================\n"
    "1. 只输出一个合法 JSON 对象，**禁止** Markdown 代码围栏、解释文字、前言结语；\n"
    "2. 每个 issue 的 id 按 ISS-001, ISS-002... 递增；\n"
    "3. statistics 中的数字必须与实际 issues 数量一致；\n"
    "4. 至少要找出 3 个问题；如果文档质量很高确实找不出，在 summary 中说明；\n"
    "5. JSON 必须合法：UTF-8、双引号、无尾随逗号、布尔小写；\n"
    "6. type 字段只能使用指定的 6 种类型之一。"
)
