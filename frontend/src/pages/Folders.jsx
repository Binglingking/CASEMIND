import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api.js';
import { useProject, useLLM } from '../store.js';
import LegacyExcelMappingDialog from '../components/LegacyExcelMappingDialog.jsx';
import LegacyCaseTable from '../components/LegacyCaseTable.jsx';
import LegacyXMindTreeView from '../components/LegacyXMindTreeView.jsx';

function formatSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return '-';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

function formatTime(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return '-';
  try { return new Date(n * 1000).toLocaleString(); } catch { return '-'; }
}

const EXT_COLORS = {
  '.pdf':  { bg: 'rgba(255,180,171,0.14)', fg: '#ffb4ab' },
  '.docx': { bg: 'rgba(131,165,255,0.14)', fg: '#9fb4ff' },
  '.md':   { bg: 'rgba(127,217,168,0.14)', fg: '#7fd9a8' },
  '.markdown': { bg: 'rgba(127,217,168,0.14)', fg: '#7fd9a8' },
  '.txt':  { bg: 'rgba(203,196,210,0.12)', fg: '#cbc4d2' },
  '.xmind': { bg: 'rgba(231,195,101,0.14)', fg: '#e7c365' },
  '.json': { bg: 'rgba(131,165,255,0.14)', fg: '#9fb4ff' },
  '.xlsx': { bg: 'rgba(127,217,168,0.14)', fg: '#7fd9a8' },
};

function ExtTag({ ext, count }) {
  const c = EXT_COLORS[ext] || { bg: 'rgba(207,188,255,0.12)', fg: '#cfbcff' };
  return (
    <span className="tag mono" style={{ background: c.bg, color: c.fg, marginRight: 6, marginBottom: 4 }}>
      {ext.replace('.', '').toUpperCase()} · {count}
    </span>
  );
}

function ScanStream({ title, lines, running, onCollapse, collapsed }) {
  const bodyRef = useRef(null);
  useEffect(() => {
    if (bodyRef.current && !collapsed) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [lines, collapsed]);
  return (
    <div className="card" style={{ margin: '0 0 16px 0', border: '1px solid rgba(207,188,255,0.2)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="mi" style={{
            color: '#cfbcff', fontSize: 18,
            animation: running ? 'pulse 1.4s infinite' : 'none',
          }}>auto_awesome</span>
          <span style={{ fontWeight: 600 }}>{title}</span>
          {running
            ? <span className="tag info">扫描中…</span>
            : <span className="tag ok">完成 · {lines.length} 条</span>}
        </div>
        <button className="ghost" style={{ padding: '4px 10px', fontSize: 12 }} onClick={onCollapse}>
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>
            {collapsed ? 'unfold_more' : 'unfold_less'}
          </span>
          {collapsed ? '展开' : '收起'}
        </button>
      </div>
      {!collapsed && (
        <pre
          ref={bodyRef}
          className="thinking-body"
          style={{ marginTop: 10, maxHeight: 220, fontSize: 12 }}
        >
          {lines.length === 0 ? '准备扫描…' : lines.join('\n')}
        </pre>
      )}
    </div>
  );
}

function FolderRow({ project, folder, onRemove, onOpenFile }) {
  const [open, setOpen] = useState(false);
  const [files, setFiles] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && files === null) {
      setLoading(true);
      try {
        const r = await api.listFolderFiles(project, folder.path);
        setFiles(r.files || []);
      } catch (e) { setErr(String(e.message || e)); setFiles([]); }
      setLoading(false);
    }
  }

  return (
    <div style={{ borderBottom: '1px solid #211f24' }}>
      <div
        className="folder-row"
        style={{ cursor: 'pointer' }}
        onClick={toggle}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
          <span className="mi" style={{ fontSize: 16 }}>
            {open ? 'expand_more' : 'chevron_right'}
          </span>
          <span className="mi">{folder.exists ? 'folder' : 'folder_off'}</span>
          <span style={{ wordBreak: 'break-all', fontSize: 13 }}>{folder.path}</span>
        </div>
        <div style={{ color: '#d8d3de' }}>{formatSize(folder.total_size)}</div>
        <div style={{ color: '#b5afbd', fontSize: 12.5 }}>
          {folder.file_count} 个文件
        </div>
        <div>
          {Object.entries(folder.by_ext || {}).slice(0, 1).map(([ext, cnt]) => (
            <ExtTag key={ext} ext={ext} count={cnt} />
          ))}
        </div>
        <div style={{ textAlign: 'right' }}>
          <button
            className="danger-ghost"
            onClick={(e) => { e.stopPropagation(); onRemove(folder.path); }}
          >移除</button>
        </div>
      </div>

      {open && (
        <div style={{ padding: '8px 40px 16px 48px', background: 'rgba(15,13,19,0.3)' }}>
          <div style={{ marginBottom: 8 }}>
            {Object.entries(folder.by_ext || {})
              .sort((a, b) => b[1] - a[1])
              .map(([ext, cnt]) => <ExtTag key={ext} ext={ext} count={cnt} />)}
          </div>
          {loading && <p className="muted">加载中...</p>}
          {err && <p className="err">{err}</p>}
          {files && !loading && (
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>文件名</th>
                    <th>相对路径</th>
                    <th>大小</th>
                    <th>修改时间</th>
                    <th>格式</th>
                  </tr>
                </thead>
                <tbody>
                  {files.map((x, i) => (
                    <tr key={x.abs_path || i}>
                      <td>
                        <a
                          onClick={(e) => { e.preventDefault(); onOpenFile(x.abs_path, x.name); }}
                          style={{ color: '#e0d2ff', cursor: 'pointer', textDecoration: 'none' }}
                          title={`打开 ${x.abs_path}`}
                          href="#"
                        >
                          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 6, color: '#cfbcff' }}>description</span>
                          <span style={{ borderBottom: '1px dashed rgba(207,188,255,0.4)' }}>{x.name || '-'}</span>
                          <span className="mi" style={{ fontSize: 12, verticalAlign: -1, marginLeft: 4, color: '#948e9c' }}>open_in_new</span>
                        </a>
                      </td>
                      <td style={{ color: '#b5afbd' }}>{x.rel_path || '-'}</td>
                      <td>{formatSize(x.size)}</td>
                      <td>{formatTime(x.mtime)}</td>
                      <td><span className="tag info mono">{(x.ext || '').replace('.', '').toUpperCase()}</span></td>
                    </tr>
                  ))}
                  {files.length === 0 && (
                    <tr><td colSpan={5} className="muted" style={{ textAlign: 'center' }}>该目录下无支持格式的文件</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RequirementsTab({ project }) {
  const [folders, setFolders] = useState([]);
  const [path, setPath] = useState('');
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [scan, setScan] = useState(null);
  const streamTimer = useRef(null);

  async function refresh() {
    setErr('');
    if (!project) { setFolders([]); return; }
    try {
      const r = await api.listFolders(project);
      setFolders(r.folders || []);
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { refresh(); }, [project]);

  function stopStream() {
    if (streamTimer.current) { clearInterval(streamTimer.current); streamTimer.current = null; }
  }
  useEffect(() => stopStream, []);

  function streamLines(newLines, onDone) {
    stopStream();
    let i = 0;
    streamTimer.current = setInterval(() => {
      const take = newLines.slice(i, i + 3);
      if (take.length === 0) {
        stopStream();
        setScan(s => s ? { ...s, running: false } : s);
        onDone?.();
        return;
      }
      i += take.length;
      setScan(s => s ? { ...s, lines: [...s.lines, ...take] } : s);
    }, 40);
  }

  async function add() {
    setMsg(''); setErr('');
    if (!project) { setErr('请先选择项目'); return; }
    if (!path.trim()) { setErr('请输入本地路径'); return; }
    const p = path.trim();
    setBusy(true);
    setScan({
      title: `扫描进度 · ${p}`,
      lines: [`▸ 接收路径：${p}`, `▸ 校验目录存在性…`],
      running: true, collapsed: false, path: p,
    });
    try {
      await api.addFolder(project, p);
      setScan(s => s ? { ...s, lines: [...s.lines, '✓ 已注册到项目', '▸ 开始遍历受支持的文件…'] } : s);

      const r = await api.listFolderFiles(project, p);
      const files = r.files || [];
      const lines = [];
      const byExt = {};
      let totalSize = 0;
      files.forEach((f, idx) => {
        byExt[f.ext] = (byExt[f.ext] || 0) + 1;
        totalSize += Number(f.size) || 0;
        lines.push(
          `  [${String(idx + 1).padStart(3, ' ')}/${files.length}] ${f.ext.padEnd(6, ' ')} ` +
          `${(f.rel_path || f.name).padEnd(50, ' ').slice(0, 50)} ${formatSize(f.size)}`
        );
      });
      const summary = [
        '',
        `▸ 遍历完成：共 ${files.length} 个文件 · ${formatSize(totalSize)}`,
        `▸ 格式分布：${Object.entries(byExt).sort((a,b)=>b[1]-a[1]).map(([k,v])=>`${k}×${v}`).join('  ')}`,
        `✓ 扫描完成`,
      ];
      streamLines([...lines, ...summary], async () => {
        setMsg(`已添加：${p}（${files.length} 文件）`);
        setPath('');
        await refresh();
      });
    } catch (e) {
      setErr(String(e.message || e));
      setScan(s => s ? { ...s, lines: [...s.lines, `✗ 失败：${e.message || e}`], running: false } : s);
    }
    setBusy(false);
  }

  async function remove(p) {
    if (!confirm(`移除路径？\n${p}\n（不会删除本地文件）`)) return;
    try {
      await api.removeFolder(project, p);
      await refresh();
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function openFile(abs, name) {
    try {
      await api.openFile(project, abs);
      setMsg(`已请求系统打开：${name}`);
      setTimeout(() => setMsg(''), 2000);
    } catch (e) { setErr(String(e.message || e)); }
  }

  const totalFiles = folders.reduce((a, f) => a + (Number(f.file_count) || 0), 0);
  const totalSize = folders.reduce((a, f) => a + (Number(f.total_size) || 0), 0);

  const extDist = useMemo(() => {
    const m = {};
    folders.forEach(f => Object.entries(f.by_ext || {}).forEach(([k, v]) => { m[k] = (m[k] || 0) + v; }));
    const total = Object.values(m).reduce((a, b) => a + b, 0) || 1;
    return Object.entries(m).sort((a, b) => b[1] - a[1]).map(([ext, cnt]) => ({ ext, cnt, pct: cnt / total }));
  }, [folders]);

  return (
    <div>
      <div className="card" style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <span className="mi" style={{ color: '#cfbcff' }}>create_new_folder</span>
        <input
          type="text" style={{ flex: 1, minWidth: 'auto' }}
          placeholder="粘贴本地文件夹绝对路径，例如 D:\docs\项目需求"
          value={path}
          onChange={e => setPath(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && add()}
        />
        <button className="primary" onClick={add} disabled={busy || !project}>
          <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>add</span>
          添加并扫描
        </button>
      </div>
      {msg && <p className="ok">{msg}</p>}
      {err && <p className="err">{err}</p>}

      {scan && (
        <ScanStream
          title={scan.title}
          lines={scan.lines}
          running={scan.running}
          collapsed={scan.collapsed}
          onCollapse={() => setScan(s => s ? { ...s, collapsed: !s.collapsed } : s)}
        />
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr', gap: 16, marginBottom: 16 }}>
        <div className="stat-card">
          <div className="stat-label">已添加路径</div>
          <div className="stat-value">{folders.length}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">总文件数</div>
          <div className="stat-value">{totalFiles.toLocaleString()}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">文件类型分布</div>
          <div style={{ marginTop: 10 }}>
            {extDist.length === 0 && <span className="muted">—</span>}
            {extDist.map(({ ext, cnt, pct }) => (
              <div key={ext} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
                <span className="mono" style={{ width: 44, color: '#d8d3de', fontSize: 12 }}>{ext.replace('.', '').toUpperCase()}</span>
                <div style={{ flex: 1, height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
                  <div style={{
                    width: `${Math.max(pct * 100, 4)}%`, height: '100%',
                    background: 'linear-gradient(90deg, #6750a4, #cfbcff)',
                  }} />
                </div>
                <span className="mono" style={{ fontSize: 12, color: '#b5afbd', width: 50, textAlign: 'right' }}>
                  {cnt.toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div className="folder-row head">
          <div>路径 / 名称</div>
          <div>大小</div>
          <div>文件数</div>
          <div>主要格式</div>
          <div></div>
        </div>
        {folders.length === 0
          ? <div style={{ padding: 32, textAlign: 'center' }} className="muted">暂无路径</div>
          : folders.map(f => (
              <FolderRow key={f.path} project={project} folder={f} onRemove={remove} onOpenFile={openFile} />
            ))
        }
        <div style={{ padding: '10px 16px', borderTop: '1px solid #211f24', color: '#948e9c', fontSize: 12, fontFamily: '"Space Grotesk", monospace' }}>
          合计 {folders.length} 个路径 · {totalFiles.toLocaleString()} 文件 · {formatSize(totalSize)}
        </div>
      </div>
    </div>
  );
}

function LegacyCaseTab({ project, llm }) {
  const [files, setFiles] = useState([]);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [selectedFileId, setSelectedFileId] = useState(''); // 选中的文件ID（用于弹窗）
  const [casesByFid, setCasesByFid] = useState({});
  const [pendingFile, setPendingFile] = useState(null);     // { headers, suggested, fingerprint, file }
  const [mappingStore, setMappingStore] = useState(null);   // ProjectColumnMappingStore
  const [mappingMgmtOpen, setMappingMgmtOpen] = useState(false);
  const [editingMapping, setEditingMapping] = useState(null); // { fingerprint, headers, suggested }
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisProgress, setAnalysisProgress] = useState(null);
  const [skipExtract, setSkipExtract] = useState(false); // 是否跳过LLM分析
  const [incremental, setIncremental] = useState(true); // 是否启用增量分析（默认开启）
  const progressTimerRef = useRef(null);
  const fileInputRef = useRef(null);

  async function loadMappingStore() {
    console.log('[LegacyCaseTab] loadMappingStore called', { project });
    try {
      const r = await api.legacyGetColumnMapping(project);
      console.log('[LegacyCaseTab] loadMappingStore result:', r);
      setMappingStore(r || { by_fingerprint: {}, stage_suffixes: [], extra_synonyms: {} });
    } catch (e) { 
      console.error('[LegacyCaseTab] loadMappingStore error:', e);
      setErr(String(e.message || e)); 
    }
  }

  async function openMappingMgmt() {
    console.log('[LegacyCaseTab] openMappingMgmt clicked', { project });
    await loadMappingStore();
    console.log('[LegacyCaseTab] mappingStore loaded:', mappingStore);
    setMappingMgmtOpen(true);
  }

  function editStoredMapping(fp, m) {
    const headers = Object.keys(m.header_to_standard || {});
    setEditingMapping({
      fingerprint: fp,
      headers,
      suggested: m.header_to_standard || {},
    });
  }

  async function saveStoredMapping(payload) {
    const { fingerprint, ...mapping } = payload;
    try {
      await api.legacyConfirmColumnMapping(project, fingerprint, mapping);
      setEditingMapping(null);
      await loadMappingStore();
      setMsg('列映射已更新');
      setTimeout(() => setMsg(''), 2000);
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function refresh() {
    if (!project) { setFiles([]); return; }
    try {
      const r = await api.legacyListCases(project);
      setFiles(r.files || []);
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { refresh(); }, [project]);

  async function uploadOne(file, confirmedMapping = null) {
    setBusy(true); setErr(''); setMsg('');
    try {
      const r = await api.legacyUploadCase(project, file, confirmedMapping);
      if (r.needs_user_confirm) {
        setPendingFile({
          headers: Object.keys(r.column_mapping?.header_to_standard || {}),
          suggested: r.column_mapping?.header_to_standard || {},
          fingerprint: r.fingerprint,
          file,
        });
      } else if (r.already_parsed) {
        setMsg(`已存在相同字节文件，跳过解析 · ${r.case_count} 用例`);
        setTimeout(() => setMsg(''), 2500);
      } else {
        const warn = r.warnings?.length ? `（${r.warnings.length} 条解析告警）` : '';
        setMsg(`已解析 ${r.case_count} 条用例 ${warn}`);
        setTimeout(() => setMsg(''), 3000);
        await refresh();
        // 上传成功后刷新列映射存储
        await loadMappingStore();
      }
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  }

  async function upload(filesArr) {
    if (!project) { setErr('请先选择项目'); return; }
    if (!filesArr || filesArr.length === 0) return;
    for (const f of filesArr) {
      await uploadOne(f);
    }
  }

  async function confirmMapping(payload) {
    if (!pendingFile) return;
    const { fingerprint, ...mapping } = payload;
    try {
      await api.legacyConfirmColumnMapping(project, fingerprint, mapping);
      // 先更新列映射存储
      await loadMappingStore();
      // 再上传文件（uploadOne内部会再次刷新，但没关系，确保数据最新）
      await uploadOne(pendingFile.file, mapping);
    } catch (e) { setErr(String(e.message || e)); }
    setPendingFile(null);
  }

  async function remove(fid, name) {
    if (!confirm(`删除历史用例 "${name}"？`)) return;
    try {
      await api.legacyDeleteCase(project, fid);
      setCasesByFid(c => { const n = { ...c }; delete n[fid]; return n; });
      if (selectedFileId === fid) setSelectedFileId('');
      await refresh();
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function toggle(fid) {
    setSelectedFileId(fid);
    if (!casesByFid[fid]) {
      try {
        const r = await api.legacyGetCaseFile(project, fid);
        setCasesByFid(c => ({ ...c, [fid]: r.cases || [] }));
      } catch (e) { setErr(String(e.message || e)); }
    }
  }

  // 组件挂载时检查是否有正在进行的分析
  useEffect(() => {
    if (!project) return;
    
    // 尝试从localStorage恢复进度
    const saved = localStorage.getItem(`analysis_progress_${project}`);
    if (saved) {
      try {
        const { analyzing: wasAnalyzing, progress: savedProgress, timestamp } = JSON.parse(saved);
        
        // 如果保存的时间在2小时内，认为可能还在运行
        const twoHoursAgo = Date.now() - 2 * 60 * 60 * 1000;
        if (timestamp > twoHoursAgo && wasAnalyzing) {
          console.log('[LegacyCaseTab] Restoring analysis progress from localStorage');
          setAnalyzing(true);
          setAnalysisProgress(savedProgress);
          
          // 立即查询一次后端确认状态
          api.legacyAnalysisProgress(project).then(progress => {
            console.log('[LegacyCaseTab] Backend progress:', progress);
            setAnalysisProgress(progress);
            
            // 如果仍在运行或暂停，启动轮询
            if (['running', 'paused'].includes(progress.status)) {
              console.log('[LegacyCaseTab] Starting progress polling');
              startProgressPolling();
            } else {
              // 已经完成，清除状态
              console.log('[LegacyCaseTab] Analysis already completed, clearing state');
              setAnalyzing(false);
              setAnalysisProgress(null);
              localStorage.removeItem(`analysis_progress_${project}`);
            }
          }).catch(err => {
            console.error('[LegacyCaseTab] Failed to restore progress:', err);
            localStorage.removeItem(`analysis_progress_${project}`);
            setAnalyzing(false);
          });
        } else {
          console.log('[LegacyCaseTab] Saved progress expired, clearing');
          localStorage.removeItem(`analysis_progress_${project}`);
        }
      } catch (e) {
        console.error('[LegacyCaseTab] Failed to parse saved progress:', e);
        localStorage.removeItem(`analysis_progress_${project}`);
      }
    }
    
    // 组件卸载时清理定时器
    return () => {
      stopProgressPolling();
    };
  }, [project]);

  async function analyze() {
    console.log('[LegacyCaseTab] analyze clicked', { project, llm });
    
    if (!llm?.api_key) { setErr('请先在「设置」填写 API Key'); return; }
    
    // 确认对话框
    let costWarning = '';
    if (skipExtract) {
      costWarning = '即将开始五阶段分析（跳过LLM信号抽取），仅更新风格画像。\n不会产生API费用，是否继续？';
    } else if (incremental) {
      costWarning = '即将开始增量分析，只处理新增或变更的用例/XMind。\n如果之前已分析过大部分数据，费用会很低。是否继续？';
    } else {
      costWarning = '即将开始完整五阶段分析，这将调用多次LLM API。\n预计会产生一定的API费用，是否继续？';
    }
    
    const confirmed = confirm(costWarning);
    if (!confirmed) return;
    
    setAnalyzing(true);
    setBusy(true);
    setErr('');
    setMsg('');
    setAnalysisProgress(null);
    
    try {
      console.log('[LegacyCaseTab] calling api.legacyAnalyze...');
      
      // 启动进度轮询
      startProgressPolling();
      
      const r = await api.legacyAnalyze(project, llm, { 
        skip_extract: skipExtract,
        incremental: incremental && !skipExtract, // 跳过LLM时不需要增量
      });
      console.log('[LegacyCaseTab] analyze result:', r);
      
      let msg = '';
      if (skipExtract) {
        msg = `分析完成（跳过LLM）· 用例 ${r.case_units_count} · 节点 ${r.xmind_leaves_count}`;
      } else if (incremental) {
        msg = `增量分析完成 · 用例 ${r.case_units_count} · 节点 ${r.xmind_leaves_count} · LLM ${r.llm_calls} · 反哺 ${r.inferred_count}`;
      } else {
        msg = `完整分析完成 · 用例 ${r.case_units_count} · 节点 ${r.xmind_leaves_count} · LLM ${r.llm_calls} · 反哺 ${r.inferred_count}`;
      }
      
      setMsg(msg);
      setTimeout(() => setMsg(''), 4000);
      await refresh();
    } catch (e) { 
      console.error('[LegacyCaseTab] analyze error:', e);
      setErr(String(e.message || e)); 
    } finally {
      stopProgressPolling();
      setBusy(false);
      setAnalyzing(false);
      setAnalysisProgress(null);
      localStorage.removeItem(`analysis_progress_${project}`);
    }
  }
  
  function startProgressPolling() {
    progressTimerRef.current = setInterval(async () => {
      try {
        const progress = await api.legacyAnalysisProgress(project);
        setAnalysisProgress(progress);
        
        // 保存到localStorage
        if (['running', 'paused'].includes(progress.status)) {
          localStorage.setItem(`analysis_progress_${project}`, JSON.stringify({
            analyzing: true,
            progress: progress,
            timestamp: Date.now()
          }));
        }
        
        // 如果已完成或取消，停止轮询
        if (['completed', 'cancelled', 'error'].includes(progress.status)) {
          stopProgressPolling();
          setAnalyzing(false);
          setBusy(false);
          setAnalysisProgress(null);
          localStorage.removeItem(`analysis_progress_${project}`);
        }
      } catch (e) {
        console.error('[LegacyCaseTab] Failed to fetch progress:', e);
      }
    }, 2000);
  }
  
  function stopProgressPolling() {
    if (progressTimerRef.current) {
      clearInterval(progressTimerRef.current);
      progressTimerRef.current = null;
    }
  }
  
  async function pauseAnalysis() {
    try {
      await api.legacyAnalysisPause(project);
      setMsg('分析已暂停');
      setTimeout(() => setMsg(''), 2000);
    } catch (e) {
      setErr('暂停失败: ' + String(e.message || e));
    }
  }
  
  async function resumeAnalysis() {
    try {
      await api.legacyAnalysisResume(project);
      setMsg('分析已继续');
      setTimeout(() => setMsg(''), 2000);
    } catch (e) {
      setErr('继续失败: ' + String(e.message || e));
    }
  }
  
  async function cancelAnalysis() {
    if (!confirm('确定要取消分析吗？已处理的数据将丢失。')) return;
    try {
      await api.legacyAnalysisCancel(project);
      setMsg('分析已取消');
      stopProgressPolling();
      setBusy(false);
      setAnalyzing(false);
      setAnalysisProgress(null);
      setTimeout(() => setMsg(''), 2000);
    } catch (e) {
      setErr('取消失败: ' + String(e.message || e));
    }
  }
  
  return (
    <div>
      <div
        className={`dropzone ${drag ? 'drag' : ''}`}
        onDragOver={e => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => {
          e.preventDefault(); setDrag(false);
          upload(Array.from(e.dataTransfer.files || []));
        }}
        onClick={() => fileInputRef.current?.click()}
        style={{ marginBottom: 12 }}
      >
        <span className="mi" style={{ fontSize: 28, color: '#7fd9a8' }}>table_chart</span>
        <div style={{ marginTop: 8, color: drag ? '#7fd9a8' : '#d8d3de', fontSize: 14 }}>
          拖拽历史 <b>Excel 用例</b>到此处，或点击上传 · 团队 10 列模板
        </div>
        <div className="muted" style={{ marginTop: 6 }}>
          首次见到新表头会弹出列映射确认；同字节内容重复上传会跳过。
        </div>
        <input
          ref={fileInputRef}
          type="file" multiple accept=".xlsx,.xls"
          style={{ display: 'none' }}
          onChange={e => { upload(Array.from(e.target.files || [])); e.target.value = ''; }}
        />
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <button className="ghost" disabled={busy || files.length === 0} onClick={analyze}>
          <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>auto_awesome</span>
          运行五阶段分析
        </button>
        <button className="ghost" onClick={openMappingMgmt}>
          <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>view_column</span>
          列映射管理
        </button>
        <label className="row" style={{ gap: 6, alignItems: 'center', cursor: 'pointer', marginLeft: 8 }}>
          <input
            type="checkbox"
            checked={incremental}
            onChange={(e) => setIncremental(e.target.checked)}
            disabled={busy || skipExtract}
          />
          <span style={{ fontSize: 12 }} title="只分析新增或变更的用例/XMind，大幅降低API费用">
            增量分析（推荐）
          </span>
        </label>
        <label className="row" style={{ gap: 6, alignItems: 'center', cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={skipExtract}
            onChange={(e) => setSkipExtract(e.target.checked)}
            disabled={busy}
          />
          <span style={{ fontSize: 12 }} title="跳过LLM信号抽取，仅更新风格画像，不产生API费用">
            跳过LLM（省费模式）
          </span>
        </label>
        <span className="muted" style={{ fontSize: 12, alignSelf: 'center' }}>
          抽取风格画像 + 反哺候选；候选需在「Memory · 反哺审核」内人工确认。
        </span>
      </div>
      
      {/* 进度显示 */}
      {analyzing && analysisProgress && (
        <div className="card" style={{ padding: 16, marginBottom: 12, background: 'rgba(127,217,168,0.05)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="mi" style={{ color: '#cfbcff', fontSize: 20 }}>analytics</span>
              <div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{analysisProgress.stage_name || '分析中...'}</div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {analysisProgress.message}
                  {analysisProgress.status === 'running' && (
                    <span style={{ marginLeft: 8, color: '#7fd9a8' }}>● 后台运行中</span>
                  )}
                  {analysisProgress.status === 'paused' && (
                    <span style={{ marginLeft: 8, color: '#ffc107' }}>● 已暂停</span>
                  )}
                </div>
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {analysisProgress.status === 'running' && (
                <button className="ghost" onClick={pauseAnalysis} style={{ fontSize: 12 }}>
                  <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>pause</span>
                  暂停
                </button>
              )}
              {analysisProgress.status === 'paused' && (
                <button className="ghost" onClick={resumeAnalysis} style={{ fontSize: 12 }}>
                  <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>play_arrow</span>
                  继续
                </button>
              )}
              <button className="danger-ghost" onClick={cancelAnalysis} style={{ fontSize: 12 }}>
                <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>stop</span>
                取消
              </button>
            </div>
          </div>
          
          {/* 进度条 */}
          <div style={{ background: '#2a2830', borderRadius: 4, height: 8, overflow: 'hidden', marginBottom: 8 }}>
            <div 
              style={{ 
                width: `${analysisProgress.progress_percent || 0}%`, 
                height: '100%',
                background: 'linear-gradient(90deg, #7fd9a8, #cfbcff)',
                transition: 'width 0.3s ease'
              }}
            />
          </div>
          
          {/* 详细信息 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12, fontSize: 12 }}>
            <div>
              <div className="muted">阶段</div>
              <div style={{ fontWeight: 600 }}>{analysisProgress.current_stage}/{analysisProgress.total_stages}</div>
            </div>
            {analysisProgress.total_batches > 0 && (
              <div>
                <div className="muted">批次</div>
                <div style={{ fontWeight: 600 }}>{analysisProgress.completed_batches}/{analysisProgress.total_batches}</div>
              </div>
            )}
            <div>
              <div className="muted">LLM调用</div>
              <div style={{ fontWeight: 600 }}>{analysisProgress.llm_calls}</div>
            </div>
            <div>
              <div className="muted">提取信号</div>
              <div style={{ fontWeight: 600 }}>{analysisProgress.extracted_signals}</div>
            </div>
            <div>
              <div className="muted">耗时</div>
              <div style={{ fontWeight: 600 }}>{Math.floor(analysisProgress.elapsed_seconds / 60)}分{Math.floor(analysisProgress.elapsed_seconds % 60)}秒</div>
            </div>
          </div>
        </div>
      )}
      
      {msg && <p className="ok">{msg}</p>}
      {err && <p className="err">{err}</p>}

      <div className="card" style={{ padding: 0, overflow: 'hidden', margin: 0 }}>
        <div className="folder-row head" style={{ gridTemplateColumns: '1fr 100px 100px 160px 60px' }}>
          <div>文件名 · @别名</div>
          <div>用例数</div>
          <div>大小</div>
          <div>上传时间</div>
          <div></div>
        </div>
        {files.length === 0 && (
          <div style={{ padding: 32, textAlign: 'center' }} className="muted">
            暂无历史用例 — 上传 .xlsx 后会自动解析与索引。
          </div>
        )}
        {files.map(f => {
          const baseName = (f.name || '').replace(/\.[^.]+$/, '');
          return (
            <div
              key={f.file_id}
              className="folder-row"
              style={{ gridTemplateColumns: '1fr 100px 100px 160px 60px', cursor: 'pointer' }}
              onClick={() => toggle(f.file_id)}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(207,188,255,0.06)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                <span className="mi" style={{ color: '#7fd9a8' }}>table_chart</span>
                <span style={{ fontSize: 13 }}>{f.name}</span>
                <code className="mono" style={{ fontSize: 11, color: '#cfbcff', background: 'rgba(207,188,255,0.08)', padding: '2px 6px', borderRadius: 4 }}>
                  @{baseName}
                </code>
                {f.analyzed && (
                  <span className="tag ok" style={{ fontSize: 11 }} title={`已分析于 ${f.analyzed_at || '未知'}`}>
                    ✓ 已分析
                  </span>
                )}
              </div>
              <div>{f.case_count ?? 0}</div>
              <div>{formatSize(f.size)}</div>
              <div style={{ color: '#b5afbd', fontSize: 12.5 }}>{f.uploaded_at || '-'}</div>
              <div style={{ textAlign: 'right' }}>
                <button
                  className="danger-ghost"
                  onClick={(e) => { e.stopPropagation(); remove(f.file_id, f.name); }}
                >删除</button>
              </div>
            </div>
          );
        })}
      </div>

      <LegacyExcelMappingDialog
        open={!!pendingFile}
        headers={pendingFile?.headers || []}
        suggested={pendingFile?.suggested || {}}
        fingerprint={pendingFile?.fingerprint || ''}
        filename={pendingFile?.file?.name || ''}
        onCancel={() => setPendingFile(null)}
        onConfirm={confirmMapping}
      />

      <LegacyExcelMappingDialog
        open={!!editingMapping}
        headers={editingMapping?.headers || []}
        suggested={editingMapping?.suggested || {}}
        fingerprint={editingMapping?.fingerprint || ''}
        filename="（编辑已保存的映射）"
        onCancel={() => setEditingMapping(null)}
        onConfirm={saveStoredMapping}
      />

      {mappingMgmtOpen && (
        <LegacyMappingManagerDialog
          store={mappingStore}
          files={files}
          onEdit={(fp, m) => editStoredMapping(fp, m)}
          onClose={() => setMappingMgmtOpen(false)}
        />
      )}

      {/* 用例文件详情弹窗 */}
      {selectedFileId && casesByFid[selectedFileId] && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            zIndex: 100,
          }}
          onClick={() => setSelectedFileId('')}
        >
          <div
            className="card"
            style={{
              width: '90vw', maxWidth: 1200, maxHeight: '90vh', overflow: 'auto',
              margin: 0, padding: 24,
            }}
            onClick={e => e.stopPropagation()}
          >
            {/* 头部 */}
            {(() => {
              const file = files.find(f => f.file_id === selectedFileId);
              return (
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 20 }}>
                  <span className="mi" style={{ fontSize: 24, color: '#7fd9a8' }}>table_chart</span>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 18, marginBottom: 4 }}>
                      {file?.name || '未知文件'}
                    </div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      {casesByFid[selectedFileId].length} 条用例
                      {file?.analyzed && ` · 已分析于 ${file.analyzed_at?.slice(0, 19) || '未知'}`}
                    </div>
                  </div>
                  <button className="ghost" onClick={() => setSelectedFileId('')}>
                    <span className="mi">close</span>
                  </button>
                </div>
              );
            })()}

            {/* 解析告警 */}
            {(() => {
              const file = files.find(f => f.file_id === selectedFileId);
              if (!file?.parse_warnings?.length) return null;
              return (
                <div style={{ marginBottom: 16 }}>
                  {file.parse_warnings.map((w, i) => (
                    <div key={i} className={w.level === 'error' ? 'err' : 'muted'} style={{ fontSize: 12, marginBottom: 4 }}>
                      [{w.level}/{w.code}] {w.message}
                      {w.row != null && ` (行 ${w.row})`}
                    </div>
                  ))}
                </div>
              );
            })()}

            {/* 用例表格 */}
            <LegacyCaseTable cases={casesByFid[selectedFileId]} />
          </div>
        </div>
      )}
    </div>
  );
}


function LegacyMappingManagerDialog({ store, files, onEdit, onClose }) {
  const entries = Object.entries(store?.by_fingerprint || {});
  const stageSuffixes = store?.stage_suffixes || [];
  const extraSynonyms = store?.extra_synonyms || {};

  // 用 column_mapping_used 反查使用了该指纹映射的文件名
  function filesUsingFp(fp, mapping) {
    const headerSet = new Set(Object.keys(mapping?.header_to_standard || {}));
    return (files || [])
      .filter(f => {
        const used = Object.keys(f.column_mapping_used || {});
        if (used.length === 0) return false;
        return used.length === headerSet.size && used.every(h => headerSet.has(h));
      })
      .map(f => f.name);
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 90,
    }}>
      <div className="card" style={{ width: 760, maxHeight: '85vh', overflow: 'auto', margin: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <span className="mi" style={{ color: '#cfbcff', fontSize: 22 }}>view_column</span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 16 }}>列映射管理</div>
            <div className="muted" style={{ fontSize: 12 }}>
              查看 / 编辑该项目内已确认的列映射（按表头指纹缓存）。同指纹的后续上传会自动复用。
            </div>
          </div>
          <button className="ghost" onClick={onClose}>关闭</button>
        </div>

        {entries.length === 0 ? (
          <div className="muted" style={{ padding: 24, textAlign: 'center' }}>
            尚无任何列映射记录 — 上传一份 Excel 后会自动出现在这里。
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {entries.map(([fp, m]) => {
              const filenames = filesUsingFp(fp, m);
              const headers = Object.keys(m.header_to_standard || {});
              const mappedCount = Object.values(m.header_to_standard || {}).filter(Boolean).length;
              return (
                <div key={fp} style={{
                  border: '1px solid #2b292f', borderRadius: 8, padding: 12,
                  background: 'rgba(15,13,19,0.3)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                    <code className="mono" style={{
                      fontSize: 11, color: '#cfbcff',
                      background: 'rgba(207,188,255,0.08)',
                      padding: '2px 6px', borderRadius: 4,
                    }}>{fp.slice(0, 12)}</code>
                    <span className={m.confirmed ? 'tag ok' : 'tag warn'}>
                      {m.confirmed ? '已确认' : '未确认'}
                    </span>
                    <span className={m.hit_ratio >= 0.9 ? 'tag ok' : 'tag warn'}>
                      命中 {(m.hit_ratio * 100).toFixed(0)}% · {mappedCount}/{headers.length}
                    </span>
                    <button
                      className="ghost"
                      style={{ marginLeft: 'auto', padding: '4px 10px', fontSize: 12 }}
                      onClick={() => onEdit(fp, m)}
                    >
                      <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>edit</span>
                      编辑
                    </button>
                  </div>
                  {filenames.length > 0 && (
                    <div className="muted" style={{ fontSize: 11.5, marginBottom: 6 }}>
                      使用此映射的文件：{filenames.join('、')}
                    </div>
                  )}
                  <div style={{
                    display: 'grid', gridTemplateColumns: '1fr 1fr',
                    gap: '4px 12px', fontSize: 12, color: '#cbc4d2',
                  }}>
                    {headers.map(h => (
                      <div key={h} style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <span className="mono" style={{ color: '#e6e0e9' }}>{h}</span>
                        <span style={{ color: m.header_to_standard[h] ? '#7fd9a8' : '#948e9c' }}>
                          → {m.header_to_standard[h] || '（忽略）'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid #2b292f' }}>
          <div className="muted mono" style={{
            fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', marginBottom: 8,
          }}>
            阶段后缀（用于子项拆分） · {stageSuffixes.length} 项
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {stageSuffixes.length === 0
              ? <span className="muted" style={{ fontSize: 12 }}>未配置</span>
              : stageSuffixes.map(s => (
                  <span key={s} className="tag info" style={{ fontSize: 11 }}>{s}</span>
                ))}
          </div>
          {Object.keys(extraSynonyms).length > 0 && (
            <>
              <div className="muted mono" style={{
                fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase',
                marginTop: 12, marginBottom: 8,
              }}>
                附加同义词
              </div>
              <div style={{ fontSize: 12, color: '#cbc4d2' }}>
                {Object.entries(extraSynonyms).map(([std, syns]) => (
                  <div key={std} style={{ marginBottom: 4 }}>
                    <span className="mono" style={{ color: '#e6e0e9' }}>{std}</span>
                    <span className="muted">: {(syns || []).join('、')}</span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}


function LegacyXMindTab({ project }) {
  const [files, setFiles] = useState([]);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [activeFid, setActiveFid] = useState('');
  const [tree, setTree] = useState(null);
  const fileInputRef = useRef(null);

  async function refresh() {
    if (!project) { setFiles([]); return; }
    try {
      const r = await api.legacyListXMind(project);
      setFiles(r.files || []);
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { refresh(); }, [project]);

  async function upload(filesArr) {
    if (!project) { setErr('请先选择项目'); return; }
    if (!filesArr || filesArr.length === 0) return;
    setBusy(true); setErr(''); setMsg('');
    try {
      for (const f of filesArr) {
        const r = await api.legacyUploadXMind(project, f);
        if (r.already_parsed) {
          setMsg(`已存在：${f.name}`);
        } else {
          setMsg(`已解析 ${r.node_count} 节点 / ${r.leaf_count} 叶子`);
        }
      }
      setTimeout(() => setMsg(''), 2500);
      await refresh();
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  }

  async function selectFile(fid) {
    if (activeFid === fid) {
      setActiveFid(''); setTree(null); return;
    }
    setActiveFid(fid); setTree(null);
    try {
      const r = await api.legacyGetXMind(project, fid);
      setTree(r.tree);
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function remove(fid, name) {
    if (!confirm(`删除 XMind "${name}"？`)) return;
    try {
      await api.legacyDeleteXMind(project, fid);
      if (activeFid === fid) { setActiveFid(''); setTree(null); }
      await refresh();
    } catch (e) { setErr(String(e.message || e)); }
  }

  return (
    <div>
      <div
        className={`dropzone ${drag ? 'drag' : ''}`}
        onDragOver={e => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={e => {
          e.preventDefault(); setDrag(false);
          upload(Array.from(e.dataTransfer.files || []));
        }}
        onClick={() => fileInputRef.current?.click()}
        style={{ marginBottom: 12 }}
      >
        <span className="mi" style={{ fontSize: 28, color: '#e7c365' }}>account_tree</span>
        <div style={{ marginTop: 8, color: drag ? '#e7c365' : '#d8d3de', fontSize: 14 }}>
          拖拽 <b>.xmind / .md</b> 到此处，或点击上传
        </div>
        <div className="muted" style={{ marginTop: 6 }}>
          .xmind 走 zipfile 原生解析；.md 走标题层级回退（团队约定无圆圈数字）。
        </div>
        <input
          ref={fileInputRef}
          type="file" multiple accept=".xmind,.md,.markdown"
          style={{ display: 'none' }}
          onChange={e => { upload(Array.from(e.target.files || [])); e.target.value = ''; }}
        />
      </div>
      {msg && <p className="ok">{msg}</p>}
      {err && <p className="err">{err}</p>}

      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 12 }}>
        <div className="card" style={{ padding: 0, overflow: 'hidden', margin: 0 }}>
          <div className="folder-row head" style={{ gridTemplateColumns: '1fr 70px 60px' }}>
            <div>文件名</div>
            <div>节点</div>
            <div></div>
          </div>
          {files.length === 0 && (
            <div style={{ padding: 24, textAlign: 'center' }} className="muted">暂无历史 XMind</div>
          )}
          {files.map(f => {
            const isOn = activeFid === f.file_id;
            return (
              <div
                key={f.file_id}
                className="folder-row"
                style={{
                  gridTemplateColumns: '1fr 70px 60px',
                  cursor: 'pointer',
                  background: isOn ? 'rgba(207,188,255,0.08)' : 'transparent',
                }}
                onClick={() => selectFile(f.file_id)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                  <span className="mi" style={{ color: '#e7c365' }}>account_tree</span>
                  <span style={{ fontSize: 13 }}>{f.name}</span>
                  {f.analyzed && (
                    <span className="tag ok" style={{ fontSize: 11 }} title={`已分析于 ${f.analyzed_at || '未知'}`}>
                      ✓ 已分析
                    </span>
                  )}
                </div>
                <div className="mono" style={{ fontSize: 12 }}>{f.node_count ?? '-'}</div>
                <div style={{ textAlign: 'right' }}>
                  <button
                    className="danger-ghost"
                    onClick={(e) => { e.stopPropagation(); remove(f.file_id, f.name); }}
                  >删</button>
                </div>
              </div>
            );
          })}
        </div>
        <div>
          <LegacyXMindTreeView tree={tree} />
        </div>
      </div>
    </div>
  );
}

export default function Folders() {
  const [project] = useProject();
  const [llm] = useLLM();
  
  // 从localStorage恢复标签页状态
  const [tab, setTab] = useState(() => {
    try {
      const saved = localStorage.getItem('folders_tab');
      if (saved && ['docs', 'cases', 'xmind'].includes(saved)) {
        return saved;
      }
    } catch (e) {
      console.error('[Folders] Failed to restore tab:', e);
    }
    return 'docs';
  });

  // 保存标签页状态到localStorage
  useEffect(() => {
    try {
      localStorage.setItem('folders_tab', tab);
    } catch (e) {
      console.error('[Folders] Failed to save tab:', e);
    }
  }, [tab]);

  // 保存和恢复滚动位置
  useEffect(() => {
    const scrollKey = `folders_scroll_${tab}`;
    
    // 组件挂载时恢复滚动位置
    const savedScroll = localStorage.getItem(scrollKey);
    if (savedScroll) {
      setTimeout(() => {
        window.scrollTo(0, parseInt(savedScroll, 10));
      }, 100); // 延迟执行，等待DOM渲染
    }
    
    // 组件卸载时保存滚动位置
    return () => {
      try {
        localStorage.setItem(scrollKey, String(window.scrollY));
      } catch (e) {
        console.error('[Folders] Failed to save scroll:', e);
      }
    };
  }, [tab]);

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="page-title">目录管理 <span className="badge-pro">PRO</span></div>
          <div className="page-sub">需求文档 / 历史用例 / 历史 XMind — 双向使用：反哺知识库 + 风格参照。</div>
        </div>
        <div className="mode-tabs">
          <button className={tab === 'docs' ? 'active' : ''} onClick={() => setTab('docs')}>
            <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4, color: '#cfbcff' }}>folder</span>
            需求文档
          </button>
          <button className={tab === 'cases' ? 'active' : ''} onClick={() => setTab('cases')}>
            <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4, color: '#7fd9a8' }}>table_chart</span>
            历史用例
          </button>
          <button className={tab === 'xmind' ? 'active' : ''} onClick={() => setTab('xmind')}>
            <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4, color: '#e7c365' }}>account_tree</span>
            历史 XMind
          </button>
        </div>
      </div>

      {tab === 'docs' && <RequirementsTab project={project} />}
      {tab === 'cases' && <LegacyCaseTab project={project} llm={llm} />}
      {tab === 'xmind' && <LegacyXMindTab project={project} />}
    </div>
  );
}
