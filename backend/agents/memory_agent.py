"""MemoryAgent — incremental diff-aware memory builder.

Pipeline:
  1. Scan all configured folders → list of ScannedFile
  2. Diff against file_index.json using (size, mtime, hash)
  3. For each new/changed file:
       parse → chunk → embed → add to vector store
       → LLM per-doc summary → cache to per_doc/<sha>.md
  4. For deleted files:
       remove from vector store + delete cached summary
  5. Synthesize memory.md from ALL cached per-doc summaries
  6. Derive memory_prompt.txt from memory.md
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from backend.agents.base import AgentBase, load_prompt
from backend.agents.memory_progress_tracker import controller_manager
from backend.config import settings
from backend.core import folders as folders_store
from backend.core.chunker import chunk_text
from backend.core.file_index import FileIndex, IndexEntry, load_index, save_index
from backend.core.file_scanner import ScannedFile, hash_file, scan_many
from backend.core.llm import LLMConfig, chat
from backend.core.parser import parse_file
from backend.core.project import project_manager
from backend.core.timeutil import utc_compact, utc_iso_z
from backend.core.vector_store import VectorStore


PER_DOC_DIR = "per_doc"


def _per_doc_dir(project: str) -> Path:
    d = project_manager.mem_dir(project) / PER_DOC_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _memory_md_path(project: str) -> Path:
    return project_manager.mem_dir(project) / "memory.md"


def _memory_prompt_path(project: str) -> Path:
    return project_manager.mem_dir(project) / "memory_prompt.txt"


class MemoryAgent(AgentBase):
    name = "memory"

    # ------------------------------------------------------------------
    # public
    # ------------------------------------------------------------------

    def scan(self) -> dict:
        """Return what would be scanned — dry-run, no index writes."""
        roots = folders_store.list_folders(self.project)
        files = scan_many(roots)
        by_root: dict[str, list[dict]] = {r: [] for r in roots}
        for f in files:
            by_root.setdefault(f.root, []).append({
                "path": f.path, "rel_path": f.rel_path,
                "size": f.size, "mtime": f.mtime,
            })
        return {
            "folders": roots,
            "file_count": len(files),
            "files_by_root": by_root,
        }

    def build(self, llm_cfg: LLMConfig, force_files: list[str] | None = None,
              rebuild_all: bool = False, incremental: bool = True) -> dict:
        """Incremental build. If rebuild_all, drop caches first."""
        roots = folders_store.list_folders(self.project)
        if not roots:
            raise RuntimeError("No folders configured — please add at least one local folder.")

        # Initialize progress controller
        controller = controller_manager.get_or_create(self.project)
        
        idx = load_index(self.project)
        store = VectorStore(self.project)

        if rebuild_all:
            # wipe per-doc + vector by re-init
            for f in _per_doc_dir(self.project).glob("*.md"):
                f.unlink()
            idx = FileIndex()
            # wipe vector store files
            for pth in [store.index_path, store.npy_path, store.meta_path]:
                if pth.exists():
                    pth.unlink()
            store = VectorStore(self.project)

        scanned = scan_many(roots)
        scanned_map = {s.path: s for s in scanned}
        
        # Start progress tracking
        controller.start(total_files=len(scanned))
        controller.update_progress(step=1, step_name="扫描文件夹", message=f"扫描到 {len(scanned)} 个文件")

        force_set = {str(Path(p).resolve()) for p in (force_files or [])}

        added, updated, skipped, removed = [], [], [], []
        log: list[str] = []
        # 收集本轮处理过的 (source_file, doc_version, chunks)——供下游 KnowledgeExtractor 用。
        extraction_batch: list[tuple[str, str, list]] = []

        try:
            # --- 1) detect removed files ---
            controller.update_progress(step=2, step_name="检测删除文件", 
                                       processed_files=0,
                                       message="正在比对索引...")
            
            for key in list(idx.files.keys()):
                if key not in scanned_map:
                    entry = idx.files.pop(key)
                    store.remove_source(_source_key(entry.path))
                    sp = project_manager.mem_dir(self.project) / entry.summary_path
                    if entry.summary_path and sp.exists():
                        sp.unlink()
                    removed.append(key)
                    log.append(f"removed: {key}")

            # --- 2) detect new / changed / force files ---
            to_process: list[ScannedFile] = []
            for sf in scanned:
                # Check for cancellation
                if controller.check_should_cancel():
                    controller.complete(error="用户取消")
                    return {"added": added, "updated": updated, "skipped": skipped, "removed": removed, "log": log}
                
                prev = idx.files.get(sf.path)
                forced = sf.path in force_set
                changed = (prev is None) or (prev.size != sf.size) or (prev.mtime != sf.mtime)
                if forced or changed:
                    to_process.append(sf)
                else:
                    skipped.append(sf.path)

            # --- 3) process each ---
            controller.update_progress(step=3, step_name="处理新增/变更文件", 
                                       processed_files=0,
                                       total_files=len(to_process),
                                       message=f"待处理 {len(to_process)} 个文件")
            
            for i, sf in enumerate(to_process):
                # Check pause
                while controller.check_should_pause():
                    time.sleep(0.5)
                    if controller.check_should_cancel():
                        controller.complete(error="用户取消")
                        return {"added": added, "updated": updated, "skipped": skipped, "removed": removed, "log": log}
                
                # Check cancel
                if controller.check_should_cancel():
                    controller.complete(error="用户取消")
                    return {"added": added, "updated": updated, "skipped": skipped, "removed": removed, "log": log}
                
                try:
                    h = hash_file(sf.path)
                except OSError as e:
                    log.append(f"hash failed: {sf.path} ({e})")
                    continue
                
                prev = idx.files.get(sf.path)
                if prev is not None and prev.hash == h and sf.path not in force_set:
                    # mtime changed but content didn't; refresh bookkeeping only
                    idx.files[sf.path] = IndexEntry(
                        path=sf.path, size=sf.size, mtime=sf.mtime, hash=h,
                        ingested_at=prev.ingested_at, summary_path=prev.summary_path,
                    )
                    skipped.append(sf.path)
                    log.append(f"unchanged (hash): {sf.path}")
                    continue

                try:
                    text = parse_file(Path(sf.path))
                except Exception as e:
                    log.append(f"parse failed: {sf.path} ({e})")
                    continue
                if not text.strip():
                    log.append(f"empty: {sf.path}")
                    continue

                # vector store: replace by source key
                src_key = _source_key(sf.path)
                if store.has_source(src_key):
                    store.remove_source(src_key)
                chunks = chunk_text(
                    text, source=src_key,
                    size=settings.chunk_size, overlap=settings.chunk_overlap,
                )
                store.add_chunks(chunks)
                doc_version = datetime.utcfromtimestamp(sf.mtime).isoformat() + "Z"
                extraction_batch.append((src_key, doc_version, chunks))

                # LLM per-doc summary (cached by hash)
                summary_file = _per_doc_dir(self.project) / f"{h}.md"
                if summary_file.exists() and sf.path not in force_set and prev and prev.hash == h:
                    summary_md = summary_file.read_text(encoding="utf-8")
                    log.append(f"reuse cache: {sf.path}")
                else:
                    summary_md = _summarize_doc(sf, text, llm_cfg)
                    summary_file.write_text(summary_md, encoding="utf-8")
                    log.append(f"summarized: {sf.path}")
                    
                    # Update LLM call count
                    controller.update_progress(llm_calls=controller.llm_calls + 1)

                rel_summary = str(summary_file.relative_to(project_manager.mem_dir(self.project)))
                idx.files[sf.path] = IndexEntry(
                    path=sf.path, size=sf.size, mtime=sf.mtime, hash=h,
                    ingested_at=utc_iso_z(),
                    summary_path=rel_summary,
                )
                if prev is None:
                    added.append(sf.path)
                else:
                    updated.append(sf.path)
                
                # Update progress
                controller.update_progress(processed_files=i + 1, 
                                          message=f"正在处理第 {i+1}/{len(to_process)} 个文件")

            save_index(self.project, idx)

            # --- 4) synthesize memory.md ---
            controller.update_progress(step=4, step_name="保存文件索引", message="正在保存索引...")
            
            controller.update_progress(step=5, step_name="合成 memory.md", message="正在调用LLM合成记忆...")
            memory_md = _synthesize_memory(self.project, idx, llm_cfg, incremental and not rebuild_all)
            _memory_md_path(self.project).write_text(memory_md, encoding="utf-8")
            controller.update_progress(llm_calls=controller.llm_calls + 1)

            # --- 5) derive memory_prompt.txt ---
            controller.update_progress(step=6, step_name="生成 prompt", message="正在生成prompt...")
            prompt_txt = _build_prompt(self.project, memory_md)
            _memory_prompt_path(self.project).write_text(prompt_txt, encoding="utf-8")

            # --- 6) 可选：结构化知识抽取（feature flag 控制） ---
            kp_result: dict | None = None
            try:
                # 延迟导入，避免 features off 时还强行加载 extractor / kp_store。
                from backend.api.routes_settings import get_runtime_features
                if get_runtime_features().enable_knowledge_extraction:
                    controller.update_progress(step=7, step_name="知识抽取", message="正在抽取知识点...")
                    from backend.agents.knowledge_extractor import KnowledgeExtractor
                    live_sources = {_source_key(p) for p in scanned_map.keys()}
                    kp_result = KnowledgeExtractor(self.project).extract_incremental(
                        changed_sources=extraction_batch,
                        llm_cfg=llm_cfg,
                        live_sources=live_sources,
                    )
                    if kp_result:
                        controller.update_progress(extracted_kps=len(kp_result.get("kps", [])))
                    log.append(f"knowledge_points: {kp_result}")
            except Exception as e:
                # 抽取失败不得影响 memory.md 产出
                log.append(f"knowledge_extraction failed (ignored): {e!r}")

            # --- 7) 反哺候选提升：将 accepted 的 IKP 转为正式 KP ---
            promoted_inferred: dict | None = None
            try:
                from backend.services.legacy_service import promote_accepted_inferred
                controller.update_progress(step=8, step_name="反哺知识提升",
                                           message="正在将审核通过的反哺候选转为正式知识点...")
                promoted_inferred = promote_accepted_inferred(self.project)
                log.append(f"promoted_inferred: {promoted_inferred}")
            except Exception as e:
                log.append(f"promote_inferred failed (ignored): {e!r}")

            controller.complete()
            
            return {
                "project": self.project,
                "roots": roots,
                "added": added,
                "updated": updated,
                "skipped": skipped,
                "removed": removed,
                "memory_md_path": str(_memory_md_path(self.project)),
                "memory_prompt_path": str(_memory_prompt_path(self.project)),
                "vector_stats": store.stats(),
                "knowledge_points": kp_result,
                "promoted_inferred": promoted_inferred,
                "log": log,
            }
            
        except Exception as e:
            controller.complete(error=str(e))
            raise

    # ------------------------------------------------------------------
    # memory read/write
    # ------------------------------------------------------------------

    def read_memory(self) -> dict:
        md = _memory_md_path(self.project)
        pt = _memory_prompt_path(self.project)
        return {
            "memory_md": md.read_text(encoding="utf-8") if md.exists() else "",
            "memory_prompt": pt.read_text(encoding="utf-8") if pt.exists() else "",
            "memory_md_path": str(md),
            "memory_prompt_path": str(pt),
        }

    def save_memory(self, memory_md: str, regenerate_prompt: bool = True) -> dict:
        _memory_md_path(self.project).write_text(memory_md, encoding="utf-8")
        if regenerate_prompt:
            pt = _build_prompt(self.project, memory_md)
            _memory_prompt_path(self.project).write_text(pt, encoding="utf-8")
        return self.read_memory()

    def save_prompt(self, prompt_text: str) -> dict:
        _memory_prompt_path(self.project).write_text(prompt_text, encoding="utf-8")
        return self.read_memory()

    # ------------------------------------------------------------------
    # augment: merge user-supplied info into memory.md
    # ------------------------------------------------------------------

    def augment(self, info: str, llm_cfg: LLMConfig, note: str = "") -> dict:
        info = (info or "").strip()
        if not info:
            raise ValueError("补充信息不能为空")
        md_path = _memory_md_path(self.project)
        current = md_path.read_text(encoding="utf-8") if md_path.exists() else ""

        sys_prompt = load_prompt("augment.txt") or DEFAULT_AUGMENT_SYS
        user = (
            f"项目: {self.project}\n\n"
            f"===== 现有 memory.md（INDEX） =====\n{current or '(空)'}\n"
            f"===== END =====\n\n"
            f"===== 用户补充信息 =====\n{info}\n"
            f"===== END =====\n\n"
            f"请输出**完整更新后**的 memory.md（保持 INDEX 风格：短、精、结构化，"
            f"新信息融入相应章节，不丢失原有条目；若新信息与原条目冲突，以新信息为准并在行末加 `(已更新)`；"
            f"若新信息引入了新模块/术语/关键词，补入对应章节）。仅输出 markdown 正文。"
        )
        raw = chat(
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user},
            ],
            cfg=llm_cfg,
            temperature=0.1,
        )
        updated = raw.strip()
        if not updated.startswith("#"):
            updated = f"# {self.project} — 系统索引\n\n" + updated
        md_path.write_text(updated + "\n", encoding="utf-8")

        prompt_txt = _build_prompt(self.project, updated)
        _memory_prompt_path(self.project).write_text(prompt_txt, encoding="utf-8")

        # append audit entry under per_doc/ for traceability
        audit_dir = _per_doc_dir(self.project)
        ts = utc_compact()
        (audit_dir / f"augment_{ts}.md").write_text(
            f"# 补充记忆 · {utc_iso_z()}\n\n"
            f"{('> ' + note) if note else ''}\n\n"
            f"## 用户提供\n\n{info}\n",
            encoding="utf-8",
        )

        return {
            "ok": True,
            "project": self.project,
            "memory_md": updated,
            "memory_md_path": str(md_path),
            "memory_prompt_path": str(_memory_prompt_path(self.project)),
            "info_chars": len(info),
        }


# ---------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------

def _source_key(abs_path: str) -> str:
    """Stable, display-friendly source key for a local file."""
    p = Path(abs_path)
    # use filename; if collisions exist, append short hash of parent dir
    return p.name


def _sample_text(text: str, limit: int = 6000) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) <= limit:
        return text
    head = text[: int(limit * 0.6)]
    tail = text[-int(limit * 0.3):]
    return head + "\n\n...[omitted middle]...\n\n" + tail


def _summarize_doc(sf: ScannedFile, text: str, llm_cfg: LLMConfig) -> str:
    sys_prompt = load_prompt("per_doc.txt") or DEFAULT_PER_DOC
    sampled = _sample_text(text, limit=6000)
    user = (
        f"文件路径: {sf.path}\n"
        f"文件大小: {sf.size} bytes\n\n"
        f"文档内容（可能被截断）:\n{sampled}"
    )
    raw = chat(
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ],
        cfg=llm_cfg,
        temperature=0.2,
    )
    header = f"# Source: `{sf.rel_path}`\n_Path: {sf.path}_\n\n"
    return header + raw.strip() + "\n"


def _synthesize_memory(project: str, idx: FileIndex, llm_cfg: LLMConfig,
                     is_incremental: bool = False) -> str:
    per_doc_dir = _per_doc_dir(project)
    summaries: list[str] = []
    for entry in idx.files.values():
        sp = project_manager.mem_dir(project) / entry.summary_path
        if sp.exists():
            summaries.append(sp.read_text(encoding="utf-8"))
    if not summaries:
        return f"# {project} — 系统记忆\n\n(尚无文档可供合成)\n"

    joined = "\n\n---\n\n".join(summaries)
    if len(joined) > 30000:
        joined = joined[:30000] + "\n\n...[context truncated]..."

    prev_memory = ""
    if is_incremental:
        mem_path = project_manager.mem_dir(project) / "memory.md"
        if mem_path.exists():
            prev = mem_path.read_text(encoding="utf-8")
            if len(prev) > 6000:
                prev = prev[:6000] + "\n\n...[previous index truncated]..."
            prev_memory = (
                "\n\n===== 上一版 memory.md（增量构建——请保留未变更模块条目，仅更新/新增变更部分）=====\n"
                f"{prev}\n"
                "===== END 上一版 =====\n"
            )

    sys_prompt = load_prompt("memory.txt") or DEFAULT_MEMORY_SYS
    user = (
        f"项目名称: {project}\n"
        f"以下是 {len(summaries)} 份逐文档结构化摘要，请合成为一份压缩后的系统理解 memory.md。\n"
        f"{prev_memory}\n"
        f"{joined}"
    )
    raw = chat(
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ],
        cfg=llm_cfg,
        temperature=0.1,
    )
    # ensure leading title
    md = raw.strip()
    if not md.startswith("#"):
        md = f"# {project} — 系统记忆\n\n" + md
    return md + "\n"


def _build_prompt(project: str, memory_md: str) -> str:
    """Deterministic prompt template wrapping memory.md."""
    tpl = load_prompt("memory_prompt.txt") or DEFAULT_PROMPT_TPL
    return tpl.replace("{{PROJECT}}", project).replace("{{MEMORY}}", memory_md.strip())


# ---------------------------------------------------------------------
# default prompts (used only when /prompts/*.txt is missing)
# ---------------------------------------------------------------------

DEFAULT_PER_DOC = (
    "你是资深文档分析专家。任务：为给定文档输出一份**结构化 Markdown 摘要**，"
    "供下游『压缩索引合成』与『RAG 检索』两个环节共同消费。\n\n"
    "核心原则（强约束）：\n"
    "1. **严格基于原文**：只抽取文档中明确出现的信息；不得基于常识、行业知识或相似系统补全；\n"
    "2. **信息忠诚**：字段名、数值、枚举、措辞保持原文一致，不改写、不归纳、不翻译；\n"
    "3. **原子条目**：每个 bullet 只承载一条事实，便于下游切片与检索；\n"
    "4. **不确定显性化**：凡是推断、跨段落拼接、含糊表述，一律放入『不确定点』，不得混入其它章节；\n"
    "5. **无内容的章节**：写 `（原文未涉及）`，**不要省略标题**，便于下游解析。\n\n"
    "必须输出的章节与要求：\n"
    "## 一句话摘要\n"
    "（≤60 字，点明文档主题与目的，不含推测）\n\n"
    "## 主要主题\n"
    "（3-6 条 bullet，覆盖文档核心议题）\n\n"
    "## 关键实体与术语\n"
    "（每条 1 行：`- 术语 — 原文定义或首次出现上下文`；含别名时写 `(别名: xxx)`）\n\n"
    "## 结构与模块（若存在）\n"
    "（列出文档描述的系统模块/子系统/组件；每条 1 行：`- 模块名 — 职责`）\n\n"
    "## 约束/规则\n"
    "（业务规则、输入约束、边界、异常路径各一条；原子化，保留原文数值与单位）\n\n"
    "## 数据与接口（若存在）\n"
    "（字段定义、枚举、接口签名；保持原文字面；格式：`- 字段/接口 — 类型/签名 — 说明`）\n\n"
    "## 不确定点\n"
    "（推测内容、冲突表述、原文含糊处；每条说明『不确定原因』）\n\n"
    "输出约束：\n"
    "- 只输出 Markdown 正文，不要代码围栏包裹整篇、不要前言结语；\n"
    "- 所有 7 个章节标题必须齐全；无内容章节写 `（原文未涉及）`；\n"
    "- 推测内容一律进入『不确定点』并以 `(推测)` 标注。"
)

DEFAULT_MEMORY_SYS = (
    "你是资深项目索引架构师。任务：基于所有逐文档摘要，合成一份**压缩索引** memory.md。\n\n"
    "定位（强约束）：\n"
    "这份 memory.md 的唯一作用是帮助 AI 在对话中**快速定位相关源文档与模块**——"
    "它**不是事实依据**。具体字段、数值、措辞、步骤、规则细节**都必须留给 RAG 检索原文**，"
    "因此 memory.md 要求**短、精、结构化、信息密度高，宁简勿详**。\n\n"
    "核心原则：\n"
    "1. **严格基于摘要**：不得编造摘要中未出现的模块、术语、流程；\n"
    "2. **每条可溯源**：每一条目末尾必须带 `源文档：xxx.md[, yyy.md]`；\n"
    "3. **同义合并**：识别并合并同义模块/术语（如『登录』=『用户认证』），取规范名，其余以 `(别名: xxx)` 标注；\n"
    "4. **推测显性化**：跨摘要推断的内容以 `(推测)` 标注，并尽量放入『未决 / 不确定』；\n"
    "5. **冲突显性化**：摘要间冲突时不擅自取舍，两方并列列出并标 `(冲突)`，归入『未决 / 不确定』。\n\n"
    "必须输出的章节与要求：\n"
    "# 项目概览\n"
    "（3-6 行：项目目标、核心业务、主要角色、关键外部依赖）\n\n"
    "# 模块目录\n"
    "（每个模块 1 行：`- 模块名 — 一句话职责 — 源文档：file1.md, file2.docx`）\n\n"
    "# 关键术语\n"
    "（每条 1 行：`- 术语 — 简释（≤30 字） — 源文档：xxx`）\n\n"
    "# 业务流程 / 数据流\n"
    "（每条 1 行提示性描述：`- 流程名：A → B → C — 源文档：xxx`，不展开步骤细节）\n\n"
    "# 约束速查\n"
    "（只列**约束类型与所在模块**，不展开具体数值：`- 登录密码复杂度约束 — 源文档：xxx`）\n\n"
    "# 关键词索引\n"
    "（**至少 30 条**，覆盖功能点/角色/流程/字段/状态/接口/异常；"
    "格式：`- 关键词：源文档1, 源文档2`；按字母或拼音排序）\n\n"
    "# 未决 / 不确定\n"
    "（推测、冲突、摘要中明确的未决项；每条注明原因）\n\n"
    "输出约束：\n"
    "- 只输出 Markdown 正文，不要代码围栏包裹整篇、不要前言结语、不要解释；\n"
    "- 所有 7 个章节标题必须齐全；无内容章节保留标题并写 `（暂无）`；\n"
    "- 每一条目必须带 `源文档：...`；推测标 `(推测)`，冲突标 `(冲突)`，别名标 `(别名: xxx)`。"
)

DEFAULT_AUGMENT_SYS = (
    "你是资深项目索引维护者。任务：把用户新提供的补充信息**融合**进现有 memory.md（一个压缩索引）。\n\n"
    "核心原则（强约束）：\n"
    "1. **保持 INDEX 风格**：短、精、条目化，不要展开成长篇正文，不要引入段落描述；\n"
    "2. **归位优先**：新信息必须优先分配到**合适的现有章节**"
    "（项目概览 / 模块目录 / 关键术语 / 业务流程 / 约束速查 / 关键词索引 / 未决）；\n"
    "3. **必要时新增**：若确无合适章节，可新增章节，但保持与现有风格（标题层级、条目格式）一致；\n"
    "4. **零丢失**：不得丢失任何既有条目；排序可调整但内容必须保留；\n"
    "5. **冲突处理**：新信息与既有条目冲突时，以新信息为准并在该行**行末追加 `(已更新)`**，"
    "原值可在『未决 / 不确定』中登记一条『历史：……（已被覆盖）』；\n"
    "6. **补充来源标注**：新增/修改的条目若来源于用户补充（而非原始文档），在行末**追加 `(补充)`**；\n"
    "7. **溯源完整**：所有条目必须带 `源文档：...`；用户未提供来源时写 `源文档：用户补充`；\n"
    "8. **同义合并**：若用户补充的概念与既有条目是同义（如补充『鉴权』而既有是『登录』），"
    "合并至既有条目，以 `(别名: 鉴权)` 追加，并在行末加 `(已更新)`，不得新建重复条目；\n"
    "9. **推测与冲突显性化**：用户补充中若含推测，保留 `(推测)` 标；若与既有条目冲突，按规则 5 处理。\n\n"
    "输出约束：\n"
    "- 输出**完整更新后的** memory.md 正文（Markdown），**不是 diff、不是增量片段**；\n"
    "- 不要解释、不要前言、不要代码围栏包裹整篇；\n"
    "- 保留原有 7 个章节标题；新增章节追加在末尾（『未决 / 不确定』之前）。"
)

DEFAULT_PROMPT_TPL = (
    "你是熟悉「{{PROJECT}}」项目的 AI 助手。\n\n"
    "====================\n"
    "双层知识源说明（强约束）\n"
    "====================\n"
    "下面的 SYSTEM INDEX 是该项目的**压缩索引**（memory.md），"
    "用于帮你**定位**相关模块和源文档——**它不是事实依据**。\n"
    "事实依据来自每次对话时随附的**『检索片段 / PRIMARY SOURCES』**，"
    "那是真正的权威原文，带有 `[文件名 #序号]` 元数据。\n\n"
    "====================\n"
    "行为规则（按顺序执行）\n"
    "====================\n"
    "1. **先读 INDEX**：了解项目全貌、模块划分、关键词与源文档对应关系，建立上下文；\n"
    "2. **主要依据『检索片段』作答**：所有具体细节"
    "（字段名、数值、枚举、步骤、措辞、规则、接口签名）必须来自检索片段，"
    "**不得基于 INDEX 推测或补全**——INDEX 中的简释只是线索，不是答案；\n"
    "3. **冲突以检索片段为准**：若检索片段与 INDEX 描述不一致，**原文优先**，"
    "并在答末以 1 行提示 `注：INDEX 描述与原文存在出入，以原文为准`；\n"
    "4. **检索片段不足以回答时**：\n"
    "   a. 如实告知信息缺失，**不得脑补**；\n"
    "   b. 根据 INDEX 指出**可能相关的源文档名**作为补救线索；\n"
    "   c. 建议用户在记忆中补充细节，或在问题中以 `@文件名` 引用该文档重新提问；\n"
    "5. **每条结论必须标注来源** `[文件名 #序号]`（来自检索片段元数据）；"
    "无法标注来源的结论，必须改写为『未在文档中找到相关信息』或归入不确定项；\n"
    "6. **推测显性化**：如确需给出推测性建议，独立成段并以 `(推测)` 开头，"
    "且不得与带引用的结论混排。\n\n"
    "====================\n"
    "回答格式建议\n"
    "====================\n"
    "- 首行：一句话直接答案（带核心引用）；\n"
    "- 随后：分条列出关键证据，每条末尾带 `[文件名 #序号]`；\n"
    "- 末尾：若有推测、缺失或冲突，单列『不确定项』段落。\n\n"
    "===== SYSTEM INDEX (memory.md) =====\n"
    "{{MEMORY}}\n"
    "===== END INDEX =====\n"
)