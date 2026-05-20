# Memory构建进度控制 - 前端实现代码

## 📝 需要修改的文件

### frontend/src/pages/Memory.jsx

#### 1. 添加状态变量（在组件开头）

```jsx
// 添加在 useState 区域（约第40行附近）
const [buildProgress, setBuildProgress] = useState(null); // { status, current_step, total_steps, ... }
const [progressPolling, setProgressPolling] = useState(false);
const progressPollRef = useRef(null);
```

#### 2. 添加进度轮询函数（在 build() 函数之后）

```jsx
// 开始轮询进度
function startProgressPolling() {
  if (progressPollRef.current) return; // 已经在轮询
  
  setProgressPolling(true);
  
  const poll = async () => {
    try {
      const progress = await api.getMemoryBuildProgress(project);
      setBuildProgress(progress);
      
      // 如果构建完成/取消/错误，停止轮询
      if (['completed', 'cancelled', 'error'].includes(progress.status)) {
        stopProgressPolling();
        
        // 刷新页面数据
        await refresh();
        await refreshVersions();
        await refreshBuilds();
        
        // 显示完成消息
        if (progress.status === 'completed') {
          setMsg(`构建完成！耗时 ${formatSeconds(progress.elapsed_seconds)}`);
        } else if (progress.status === 'cancelled') {
          setMsg('构建已取消，已有记忆已保留');
        } else if (progress.status === 'error') {
          setErr(`构建失败: ${progress.error || '未知错误'}`);
        }
        
        setBusy(false);
        setBuildBusy(project, false);
      }
    } catch (e) {
      console.error('Failed to fetch progress:', e);
    }
  };
  
  // 立即执行一次
  poll();
  
  // 每2秒轮询一次
  progressPollRef.current = setInterval(poll, 2000);
}

// 停止轮询进度
function stopProgressPolling() {
  if (progressPollRef.current) {
    clearInterval(progressPollRef.current);
    progressPollRef.current = null;
  }
  setProgressPolling(false);
}

// 暂停构建
async function pauseBuild() {
  try {
    await api.pauseMemoryBuild(project);
    setMsg('暂停请求已发送，将在当前文件处理完成后暂停');
  } catch (e) {
    setErr(String(e.message || e));
  }
}

// 继续构建
async function resumeBuild() {
  try {
    await api.resumeMemoryBuild(project);
    setMsg('继续构建');
  } catch (e) {
    setErr(String(e.message || e));
  }
}

// 取消构建
async function cancelBuild() {
  if (!confirm('确定要取消构建吗？\n\n已生成的 memory.md 和 prompt 将保留。\n未完成的处理将停止。')) {
    return;
  }
  
  try {
    await api.cancelMemoryBuild(project);
    setMsg('取消请求已发送');
    stopProgressPolling();
    setBusy(false);
    setBuildBusy(project, false);
  } catch (e) {
    setErr(String(e.message || e));
  }
}

// 格式化秒数为 mm:ss
function formatSeconds(seconds) {
  if (!seconds && seconds !== 0) return '0:00';
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// 清理轮询器（组件卸载时）
useEffect(() => {
  return () => {
    stopProgressPolling();
  };
}, []);
```

#### 3. 修改 build() 函数

```jsx
async function build() {
  if (!project) { setErr('请先选择项目'); return; }
  if (!llm.api_key) { setErr('请先在「设置」填写 API Key'); return; }
  if (isBuildCooldown(project)) { setErr('构建冷却中，请稍后再试'); return; }
  
  setBusy(true); 
  setMsg(''); 
  setErr(''); 
  setLog([]); 
  setResult(null);
  setBuildProgress(null); // 重置进度
  setBuildBusy(project, true);
  
  try {
    // 启动后台构建（异步）
    const buildPromise = api.buildMemory(project, llm, {
      rebuild_all: rebuildAll,
      incremental: incremental && !rebuildAll,
    });
    
    // 立即开始轮询进度
    startProgressPolling();
    
    // 等待构建完成
    const r = await buildPromise;
    
    // 构建完成后的处理（由轮询器处理，这里只是兜底）
    if (!buildProgress || buildProgress.status !== 'completed') {
      setResult(r);
      setLog(r.log || []);
      const buildMsg = (
        `已完成：新增 ${r.added?.length || 0} · 更新 ${r.updated?.length || 0}` +
        ` · 跳过 ${r.skipped?.length || 0} · 删除 ${r.removed?.length || 0}`
      );
      setMsg(buildMsg);
      setLastBuild(project, {
        finishedAt: new Date().toISOString(),
        summary: buildMsg,
        added: r.added?.length || 0,
        updated: r.updated?.length || 0,
        skipped: r.skipped?.length || 0,
        removed: r.removed?.length || 0,
        type: rebuildAll ? 'full' : 'incremental',
      });
      await refresh();
      await refreshVersions();
      await refreshBuilds();
      setBusy(false);
      setBuildBusy(project, false);
      stopProgressPolling();
    }
  } catch (e) { 
    setErr(String(e.message || e)); 
    setBusy(false);
    setBuildBusy(project, false);
    stopProgressPolling();
  }
}
```

#### 4. 添加进度卡片UI（在构建按钮下方，约第428行后）

```jsx
{/* 进度卡片 */}
{busy && buildProgress && (
  <div className="card" style={{ 
    marginBottom: 16,
    borderColor: buildProgress.status === 'paused' ? 'rgba(231,195,101,0.3)' : 'rgba(103,80,164,0.3)',
    background: buildProgress.status === 'paused' ? 'rgba(231,195,101,0.05)' : 'rgba(103,80,164,0.05)',
  }}>
    <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
      <h3 style={{ margin: 0, fontSize: 14 }}>
        <span className="mi" style={{ 
          fontSize: 16, 
          verticalAlign: -2, 
          marginRight: 6,
          color: buildProgress.status === 'paused' ? '#e7c365' : '#cfbcff',
          animation: buildProgress.status === 'running' ? 'pulse 1.4s infinite' : 'none',
        }}>
          {buildProgress.status === 'paused' ? 'pause_circle' : 
           buildProgress.status === 'running' ? 'autorenew' : 'info'}
        </span>
        构建进度
        {buildProgress.status === 'paused' && (
          <span className="tag" style={{ marginLeft: 8, background: 'rgba(231,195,101,0.15)', color: '#e7c365' }}>
            已暂停
          </span>
        )}
      </h3>
      <div className="row" style={{ gap: 8 }}>
        {buildProgress.status === 'running' && (
          <button 
            className="ghost" 
            onClick={pauseBuild}
            style={{ padding: '4px 10px', fontSize: 12 }}
          >
            <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>pause</span>
            暂停
          </button>
        )}
        {buildProgress.status === 'paused' && (
          <button 
            className="primary" 
            onClick={resumeBuild}
            style={{ padding: '4px 10px', fontSize: 12 }}
          >
            <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>play_arrow</span>
            继续
          </button>
        )}
        <button 
          className="ghost" 
          onClick={cancelBuild}
          style={{ 
            padding: '4px 10px', 
            fontSize: 12,
            color: '#e7c365',
          }}
        >
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>stop</span>
          取消
        </button>
      </div>
    </div>
    
    {/* 进度条 */}
    <div style={{ 
      width: '100%', 
      height: 6, 
      background: 'rgba(255,255,255,0.1)', 
      borderRadius: 3,
      marginBottom: 12,
      overflow: 'hidden',
    }}>
      <div style={{
        width: `${buildProgress.progress_percent || 0}%`,
        height: '100%',
        background: buildProgress.status === 'paused' 
          ? 'linear-gradient(90deg, #e7c365, #f0d87a)' 
          : 'linear-gradient(90deg, #cfbcff, #b8a5e8)',
        borderRadius: 3,
        transition: 'width 0.3s ease',
      }} />
    </div>
    
    {/* 详细信息 */}
    <div style={{ 
      display: 'grid', 
      gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', 
      gap: 12,
      fontSize: 12,
    }}>
      <div>
        <div style={{ color: '#948e9c', marginBottom: 4 }}>当前步骤</div>
        <div style={{ color: '#e6e0e9', fontWeight: 500 }}>
          {buildProgress.step_name || '准备中...'} ({buildProgress.current_step}/{buildProgress.total_steps})
        </div>
      </div>
      
      <div>
        <div style={{ color: '#948e9c', marginBottom: 4 }}>文件进度</div>
        <div style={{ color: '#e6e0e9', fontWeight: 500 }}>
          {buildProgress.processed_files}/{buildProgress.total_files}
        </div>
      </div>
      
      <div>
        <div style={{ color: '#948e9c', marginBottom: 4 }}>LLM调用</div>
        <div style={{ color: '#cfbcff', fontWeight: 500 }}>
          {buildProgress.llm_calls} 次
        </div>
      </div>
      
      <div>
        <div style={{ color: '#948e9c', marginBottom: 4 }}>知识点</div>
        <div style={{ color: '#7fd9a8', fontWeight: 500 }}>
          {buildProgress.extracted_kps} 个
        </div>
      </div>
      
      <div>
        <div style={{ color: '#948e9c', marginBottom: 4 }}>耗时</div>
        <div style={{ color: '#e6e0e9', fontWeight: 500 }}>
          {formatSeconds(buildProgress.elapsed_seconds)}
        </div>
      </div>
    </div>
    
    {buildProgress.message && (
      <div style={{ marginTop: 10, fontSize: 11, color: '#948e9c' }}>
        <span className="mi" style={{ fontSize: 12, verticalAlign: -2, marginRight: 4 }}>info</span>
        {buildProgress.message}
      </div>
    )}
  </div>
)}
```

#### 5. 修改构建按钮的状态（约第399-415行）

```jsx
<button
  className="primary"
  onClick={build}
  disabled={busy || !project || cooldown}
  title={cooldown ? '请稍等片刻再构建' : busy ? '构建中…' : !project ? '请先选择项目' : '开始构建AI记忆'}
  style={busy ? {
    background: 'linear-gradient(135deg, #e7c365, #cfbcff)',
    opacity: 0.7,
    cursor: 'not-allowed',
  } : cooldown ? {
    background: '#494551', color: '#948e9c', boxShadow: 'none',
  } : {}}
>
  <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>
    {busy ? 'autorenew' : cooldown ? 'lock' : 'build'}
  </span>
  {busy ? '构建中…' : cooldown ? '冷却中…' : '构建 AI 记忆'}
</button>
```

#### 6. 添加CSS动画（在全局样式文件中，或在组件内添加style标签）

```css
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
```

## 🔧 后端集成说明

### 需要在 memory_agent.py 中添加的进度更新点

在 `backend/agents/memory_agent.py` 的 `build()` 方法中，需要在关键位置添加进度更新：

```python
from backend.agents.memory_progress_tracker import controller_manager

def build(self, llm_cfg: LLMConfig, force_files: list[str] | None = None,
          rebuild_all: bool = False, incremental: bool = True) -> dict:
    """Incremental build. If rebuild_all, drop caches first."""
    roots = folders_store.list_folders(self.project)
    if not roots:
        raise RuntimeError("No folders configured — please add at least one local folder.")

    # 初始化进度跟踪器
    controller = controller_manager.get_or_create(self.project)
    controller.start(total_files=0)  # 稍后更新
    
    try:
        # Step 1: 扫描文件夹
        controller.update_progress(step=1, step_name="扫描文件夹", message="正在扫描配置的文件夹...")
        
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
        
        # 更新总文件数
        controller.update_progress(total_files=len(scanned))

        force_set = {str(Path(p).resolve()) for p in (force_files or [])}

        added, updated, skipped, removed = [], [], [], []
        log: list[str] = []
        extraction_batch: list[tuple[str, str, list]] = []

        # --- 1) detect removed files ---
        controller.update_progress(step=2, step_name="检测删除文件", message=f"检测到 {len(list(idx.files.keys()))} 个索引文件...")
        
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
            # 检查是否应该取消
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
                                   message=f"待处理 {len(to_process)} 个文件...")
        
        for i, sf in enumerate(to_process):
            # 检查暂停
            while controller.check_should_pause():
                time.sleep(0.5)
                if controller.check_should_cancel():
                    controller.complete(error="用户取消")
                    return {"added": added, "updated": updated, "skipped": skipped, "removed": removed, "log": log}
            
            # 检查取消
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
                
                # 更新LLM调用计数
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
            
            # 更新进度
            controller.update_progress(processed_files=i + 1, 
                                      message=f"正在处理第 {i+1}/{len(to_process)} 个文件...")

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

## ✅ 测试清单

1. **基本功能**
   - [ ] 点击"构建 AI 记忆"按钮后显示进度卡片
   - [ ] 进度条实时更新
   - [ ] 当前步骤正确显示
   - [ ] 文件数量、LLM调用次数正确统计

2. **暂停/继续**
   - [ ] 点击"暂停"后，构建在当前文件处理完成后暂停
   - [ ] 暂停状态下显示"已暂停"标签
   - [ ] 点击"继续"后，从暂停处继续构建

3. **取消**
   - [ ] 点击"取消"后有二次确认对话框
   - [ ] 取消后进度卡片消失
   - [ ] 已有的memory.md和prompt保留
   - [ ] 可以正常查看之前的版本

4. **异常情况**
   - [ ] 刷新页面后，如果构建仍在进行，能恢复进度显示
   - [ ] 构建出错时显示错误信息
   - [ ] 网络中断不影响本地状态

5. **用户体验**
   - [ ] 进度更新流畅，不卡顿
   - [ ] 按钮状态正确（禁用/启用）
   - [ ] 提示信息清晰易懂

## 🎯 预期效果

实现后，用户将获得：
- 清晰的实时进度可视化
- 完全的控制权（暂停/继续/取消）
- 安全的取消机制（保护已有记忆）
- 更好的费用控制能力
- 专业的用户体验
