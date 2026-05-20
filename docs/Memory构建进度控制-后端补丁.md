# Memory Agent 进度跟踪集成补丁

## 修改 backend/agents/memory_agent.py 的 build() 方法

### 在 build() 方法开头添加（第74行后）：

```python
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

        # --- 6) Optional: knowledge extraction ---
        kp_result: dict | None = None
        try:
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
        except Exception as e:
            log.append(f"knowledge extraction failed: {e}")

        controller.complete()
        
        return {
            "added": added,
            "updated": updated,
            "skipped": skipped,
            "removed": removed,
            "log": log,
            "kp_result": kp_result,
        }
        
    except Exception as e:
        controller.complete(error=str(e))
        raise
```

## 关键点说明

1. **初始化控制器**：在方法开始时获取或创建进度控制器
2. **启动跟踪**：调用 `controller.start()` 设置总文件数
3. **更新进度**：在每个关键步骤调用 `controller.update_progress()`
4. **检查暂停**：在处理每个文件前检查是否应该暂停
5. **检查取消**：定期检查是否应该取消
6. **完成标记**：成功时调用 `controller.complete()`，失败时传入error参数
7. **异常处理**：用try-except包裹整个流程，确保异常时也能正确标记状态

## 注意事项

- 暂停时使用 `while` 循环等待，避免忙等待消耗CPU
- 每次LLM调用后更新 `llm_calls` 计数
- 文件处理过程中实时更新 `processed_files`
- 错误信息会被记录到控制器的 `error` 字段
