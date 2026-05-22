import React, { useEffect, useMemo, useState, useRef } from 'react';
import { api } from '../api.js';
import { useLLM, useProject } from '../store.js';

const LS_LAST_BUILD = (project) => `casemind.lastBuild.${project}`;
const LS_BUILD_BUSY = (project) => `casemind.buildBusy.${project}`;
const COOLDOWN_MS = 5000; // 构建冷却时间（5秒）

function getLastBuild(project) {
  try { return JSON.parse(localStorage.getItem(LS_LAST_BUILD(project)) || 'null'); }
  catch { return null; }
}
function setLastBuild(project, data) {
  if (data) localStorage.setItem(LS_LAST_BUILD(project), JSON.stringify(data));
  else localStorage.removeItem(LS_LAST_BUILD(project));
}
function getBuildBusy(project) {
  return localStorage.getItem(LS_BUILD_BUSY(project)) === '1';
}
function setBuildBusy(project, v) {
  if (v) localStorage.setItem(LS_BUILD_BUSY(project), '1');
  else localStorage.removeItem(LS_BUILD_BUSY(project));
}
function formatTimeStr(iso) {
  if (!iso) return '-';
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}
function elapsed(started, finished) {
  if (!started || !finished) return '-';
  const ms = new Date(finished) - new Date(started);
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = s / 60;
  return `${m.toFixed(1)}min`;
}
function isBuildCooldown(project) {
  const lb = getLastBuild(project);
  if (!lb?.finishedAt) return false;
  return (Date.now() - new Date(lb.finishedAt).getTime()) < COOLDOWN_MS;
}

function Stat({ label, value, icon, tone }) {
  const color = {
    add: '#7fd9a8', upd: '#e7c365', skip: '#cbc4d2', del: '#ffb4ab',
  }[tone] || '#cfbcff';
  return (
    <div className="stat-card">
      <div className="stat-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className="mi" style={{ fontSize: 14, color }}>{icon}</span>
        {label}
      </div>
      <div className="stat-value" style={{ color }}>{value}</div>
    </div>
  );
}

export default function Memory() {
  const [project] = useProject();
  const [llm] = useLLM();
  const [memory, setMemory] = useState('');
  const [prompt, setPrompt] = useState('');
  const [log, setLog] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [err, setErr] = useState('');
  const [rebuildAll, setRebuildAll] = useState(false);
  const [incremental, setIncremental] = useState(true);
  const [editingMem, setEditingMem] = useState(false);
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [result, setResult] = useState(null);
  const [tab, setTab] = useState('memory'); // memory | prompt | log | versions | builds | inferred
  const [versions, setVersions] = useState([]);
  const [builds, setBuilds] = useState([]);
  const [previewVersion, setPreviewVersion] = useState(null);
  const [previewBuild, setPreviewBuild] = useState(null);
  const [inferred, setInferred] = useState([]);
  const [inferredFilter, setInferredFilter] = useState('pending'); // pending | accepted | rejected | all
  const [inferredErr, setInferredErr] = useState('');
  const [selectedInferred, setSelectedInferred] = useState(new Set()); // 选中的反哺候选ID
  const [currentPage, setCurrentPage] = useState(1); // 当前页码
  const [pageSize, setPageSize] = useState(10); // 每页显示数量
  const [editingInferredId, setEditingInferredId] = useState(null); // 正在编辑的 IKP ID
  const [editingContent, setEditingContent] = useState(''); // 编辑中的内容
  const [expandedSources, setExpandedSources] = useState(new Set()); // 展开的聚合源
  
  // Memory build progress tracking
  const [buildProgress, setBuildProgress] = useState(null);
  const [progressPolling, setProgressPolling] = useState(false);
  const progressPollRef = useRef(null);

  async function refresh() {
    setErr('');
    if (!project) return;
    try {
      const r = await api.getMemory(project);
      setMemory(r.memory_md || '');
      setPrompt(r.memory_prompt || '');
    } catch (e) { setErr(String(e.message || e)); }
  }
  useEffect(() => { refresh(); }, [project]);

  async function refreshVersions() {
    if (!project) { setVersions([]); return; }
    try {
      const r = await api.listVersions(project);
      setVersions(r.versions || []);
    } catch { setVersions([]); }
  }

  async function refreshBuilds() {
    if (!project) { setBuilds([]); return; }
    try {
      const r = await api.listBuilds(project);
      setBuilds(r.builds || []);
    } catch { setBuilds([]); }
  }

  async function refreshInferred() {
    setInferredErr('');
    if (!project) { setInferred([]); return; }
    try {
      const status = inferredFilter === 'all' ? null : inferredFilter;
      const r = await api.legacyListInferred(project, status);
      setInferred(Array.isArray(r) ? r : (r.items || []));
    } catch (e) {
      setInferredErr(String(e.message || e));
      setInferred([]);
    }
  }

  useEffect(() => {
    if (tab === 'inferred') refreshInferred();
    // eslint-disable-next-line
  }, [tab, inferredFilter, project]);

  async function reviewInferred(item, decision) {
    try {
      await api.legacyReviewInferred(project, item.inferred_id, decision);
      refreshInferred();
      // 如果选中了该项，从选中集合中移除
      if (selectedInferred.has(item.inferred_id)) {
        const newSelected = new Set(selectedInferred);
        newSelected.delete(item.inferred_id);
        setSelectedInferred(newSelected);
      }
    } catch (e) {
      setInferredErr(String(e.message || e));
    }
  }

  // 批量审核功能
  async function batchReviewInferred(decision) {
    if (selectedInferred.size === 0) {
      setInferredErr('请先选择要审核的候选项');
      return;
    }
    
    try {
      const selectedIds = Array.from(selectedInferred);
      await api.legacyBatchReviewInferred(project, selectedIds, decision);
      setSelectedInferred(new Set()); // 清空选择
      refreshInferred();
    } catch (e) {
      setInferredErr(String(e.message || e));
    }
  }

  // 撤销 AI 自动通过
  async function revokeAutoAccepted(item) {
    try {
      await api.legacyRevokeInferred(project, item.inferred_id);
      refreshInferred();
    } catch (e) {
      setInferredErr(String(e.message || e));
    }
  }

  // 开始编辑内容
  function startEditInferred(item) {
    setEditingInferredId(item.inferred_id);
    setEditingContent(item.content || '');
  }

  // 取消编辑
  function cancelEditInferred() {
    setEditingInferredId(null);
    setEditingContent('');
  }

  // 保存编辑
  async function saveEditInferred(item) {
    if (!editingContent.trim()) {
      setInferredErr('内容不能为空');
      return;
    }
    try {
      await api.legacyEditInferred(project, item.inferred_id, editingContent.trim());
      setEditingInferredId(null);
      setEditingContent('');
      refreshInferred();
    } catch (e) {
      setInferredErr(String(e.message || e));
    }
  }

  // 切换聚合源展开
  function toggleSourceExpand(inferredId) {
    const next = new Set(expandedSources);
    if (next.has(inferredId)) {
      next.delete(inferredId);
    } else {
      next.add(inferredId);
    }
    setExpandedSources(next);
  }

  // 切换单个选择
  function toggleSelectInferred(inferredId) {
    const newSelected = new Set(selectedInferred);
    if (newSelected.has(inferredId)) {
      newSelected.delete(inferredId);
    } else {
      newSelected.add(inferredId);
    }
    setSelectedInferred(newSelected);
  }

  // 全选/取消全选（当前页）
  function toggleSelectAll() {
    const currentPageItems = getCurrentPageItems();
    if (selectedInferred.size === currentPageItems.length && currentPageItems.length > 0) {
      // 如果当前页所有项都已选中，则取消全选
      const newSelected = new Set(selectedInferred);
      currentPageItems.forEach(item => newSelected.delete(item.inferred_id));
      setSelectedInferred(newSelected);
    } else {
      // 否则全选当前页
      const newSelected = new Set(selectedInferred);
      currentPageItems.forEach(item => newSelected.add(item.inferred_id));
      setSelectedInferred(newSelected);
    }
  }

  // 获取当前页的项目
  function getCurrentPageItems() {
    const startIndex = (currentPage - 1) * pageSize;
    const endIndex = startIndex + pageSize;
    return inferred.slice(startIndex, endIndex);
  }

  // 计算总页数
  const totalPages = Math.ceil(inferred.length / pageSize);

  // 分页控制
  function goToPage(page) {
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page);
    }
  }

  // 当筛选条件改变时重置页码
  useEffect(() => {
    setCurrentPage(1);
  }, [inferredFilter]);

  useEffect(() => {
    refreshVersions();
    refreshBuilds();
  }, [project]);

  // check for unfinished build from previous session
  const lastBuild = useMemo(() => getLastBuild(project), [project]);
  const wasBuilding = useMemo(() => getBuildBusy(project), [project]);
  const cooldown = useMemo(() => isBuildCooldown(project), [project, lastBuild]);

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

  async function saveMem() {
    try {
      await api.saveMemory(project, memory, true);
      setEditingMem(false);
      setMsg('memory.md 已保存，prompt 已同步重建（新版本已记录）');
      setLastBuild(project, {
        ...getLastBuild(project),
        editedAt: new Date().toISOString(),
      });
      await refresh();
      await refreshVersions();
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function restoreFromBuild(buildId) {
    if (!confirm(`恢复到构建 #${buildId} 时的记忆状态？当前 memory.md 将被替换。`)) return;
    try {
      await api.restoreFromBuild(project, buildId);
      setMsg(`已恢复到构建 #${buildId}`);
      await refresh();
      await refreshVersions();
      await refreshBuilds();
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function savePrompt() {
    try {
      await api.savePrompt(project, prompt);
      setEditingPrompt(false);
      setMsg('memory_prompt.txt 已保存');
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function viewVersion(vId) {
    if (previewVersion?.id === vId) { setPreviewVersion(null); return; }
    try {
      const r = await api.getVersion(project, vId);
      setPreviewVersion(r);
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function restoreVersion(vId) {
    if (!confirm(`恢复到版本 ${vId}？当前 memory.md 将被替换。`)) return;
    try {
      await api.restoreVersion(project, vId);
      setMsg(`已恢复到 ${vId}`);
      await refresh();
      await refreshVersions();
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function viewBuild(bId) {
    if (previewBuild?.id === bId) { setPreviewBuild(null); return; }
    try {
      const r = await api.getBuild(project, bId);
      setPreviewBuild({ id: bId, ...r });
    } catch (e) { setErr(String(e.message || e)); }
  }

  const resultStats = result ? {
    added: (result.added || []).length,
    updated: (result.updated || []).length,
    skipped: (result.skipped || []).length,
    removed: (result.removed || []).length,
  } : null;

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="page-title">
            记忆面板 <span className="badge-pro">PRO</span>
            {lastBuild && !busy && (
              <span style={{ fontSize: 12, fontWeight: 400, color: '#948e9c', marginLeft: 10 }}>
                <span className="mi" style={{ fontSize: 11, verticalAlign: -1, marginRight: 3 }}>schedule</span>
                上次构建：{formatTimeStr(lastBuild.finishedAt)}
                {lastBuild.type === 'full' ? ' · 全量' : ' · 增量'}
              </span>
            )}
            {busy && (
              <span className="tag info" style={{ marginLeft: 10 }}>
                <span className="mi" style={{ fontSize: 12, animation: 'pulse 1.4s infinite' }}>autorenew</span>
                构建中…
              </span>
            )}
          </div>
          <div className="page-sub">构建项目知识索引，支持增量和全量模式。</div>
        </div>
      </div>

      {wasBuilding && lastBuild && !busy && (
        <div className="card" style={{
          borderColor: 'rgba(231,195,101,0.3)',
          background: 'rgba(231,195,101,0.05)',
          marginBottom: 16,
        }}>
          <span className="mi" style={{ color: '#e7c365', verticalAlign: -2, marginRight: 6 }}>warning</span>
          <span style={{ color: '#e6e0e9', fontSize: 13 }}>
            检测到上次构建可能未完成（{formatTimeStr(lastBuild.finishedAt)}）。
            如需恢复，可在「版本历史」中查看最近的版本。
          </span>
        </div>
      )}
      {msg && <p className="ok" style={{ marginLeft: 4 }}>{msg}</p>}
      {err && <p className="err">{err}</p>}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="row" style={{ alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <label className="row" style={{ gap: 6, alignItems: 'center', cursor: 'pointer' }}>
            <input
              type="radio"
              name="buildMode"
              checked={incremental}
              onChange={() => { setIncremental(true); setRebuildAll(false); }}
              disabled={busy}
            />
            <span className="mi" style={{ fontSize: 14, color: '#7fd9a8' }}>sync</span>
            <span style={{ fontSize: 13 }}>增量构建（推荐）</span>
          </label>
          <label className="row" style={{ gap: 6, alignItems: 'center', cursor: 'pointer' }}>
            <input
              type="radio"
              name="buildMode"
              checked={rebuildAll}
              onChange={() => { setIncremental(false); setRebuildAll(true); }}
              disabled={busy}
            />
            <span className="mi" style={{ fontSize: 14, color: '#e7c365' }}>restart_alt</span>
            <span style={{ fontSize: 13 }}>强制完全重建</span>
          </label>
          <div style={{ flex: 1 }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {busy && (
              <span style={{ fontSize: 12, color: '#e7c365', display: 'flex', alignItems: 'center', gap: 4 }}>
                <span className="mi" style={{ fontSize: 14, animation: 'pulse 1.4s infinite' }}>autorenew</span>
                正在分析文档…
              </span>
            )}
            {!busy && lastBuild && !cooldown && (
              <span style={{ fontSize: 11, color: '#948e9c' }} title="上次构建">
                <span className="mi" style={{ fontSize: 12, verticalAlign: -2 }}>schedule</span>
                {' '}上次: {formatTimeStr(lastBuild.finishedAt)}
              </span>
            )}
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
          </div>
        </div>
        <div className="muted" style={{ marginTop: 10, fontSize: 12 }}>
          增量构建：比对文件大小/修改时间/哈希，仅处理新增或变更文件，保留未变文件的缓存摘要。
          强制完全重建：清空全部缓存（逐文档摘要 + 向量索引），重新处理所有文件，生成全新 memory.md。
          {cooldown && !busy && (
            <span style={{ color: '#e7c365', marginLeft: 8 }}>
              <span className="mi" style={{ fontSize: 12, verticalAlign: -2 }}>info</span>
              {' '}构建完成不久，请稍等 {Math.ceil((COOLDOWN_MS - (Date.now() - new Date(lastBuild.finishedAt).getTime())) / 1000)} 秒
            </span>
          )}
        </div>
      </div>

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

      <div className="row" style={{ gap: 10, margin: '12px 0' }}>
        <button className="ghost" style={{ padding: '6px 14px', fontSize: 12 }} onClick={() => setTab('memory')}>
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>description</span>
          memory.md
        </button>
        <button className="ghost" style={{ padding: '6px 14px', fontSize: 12 }} onClick={() => setTab('prompt')}>
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>code</span>
          Prompt
        </button>
        <button className="ghost" style={{ padding: '6px 14px', fontSize: 12 }} onClick={() => setTab('log')}>
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>list_alt</span>
          构建日志
        </button>
        <button className="ghost" style={{ padding: '6px 14px', fontSize: 12 }} onClick={() => { setTab('versions'); refreshVersions(); }}>
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>history</span>
          版本历史
          {versions.length > 0 && <span className="tag info" style={{ marginLeft: 4, fontSize: 10, padding: '1px 5px' }}>{versions.length}</span>}
        </button>
        <button className="ghost" style={{ padding: '6px 14px', fontSize: 12 }} onClick={() => { setTab('builds'); refreshBuilds(); }}>
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>build_circle</span>
          构建历史
          {builds.length > 0 && <span className="tag info" style={{ marginLeft: 4, fontSize: 10, padding: '1px 5px' }}>{builds.length}</span>}
        </button>
        <button className="ghost" style={{ padding: '6px 14px', fontSize: 12 }} onClick={() => setTab('inferred')}>
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>auto_awesome</span>
          反哺审核
        </button>
      </div>

      {resultStats && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
          <Stat label="新增" value={resultStats.added} icon="add_circle" tone="add" />
          <Stat label="更新" value={resultStats.updated} icon="sync" tone="upd" />
          <Stat label="跳过" value={resultStats.skipped} icon="check_circle" tone="skip" />
          <Stat label="删除" value={resultStats.removed} icon="remove_circle" tone="del" />
        </div>
      )}

      {tab === 'memory' && (
        <div className="card">
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
            <h3 style={{ margin: 0 }}>memory.md</h3>
            <div className="row" style={{ gap: 6 }}>
              {editingMem ? (
                <>
                  <button className="ghost" onClick={() => { setEditingMem(false); refresh(); }}>取消</button>
                  <button className="primary" onClick={saveMem}>保存</button>
                </>
              ) : (
                <button className="ghost" onClick={() => setEditingMem(true)}>
                  <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>edit</span>
                  编辑
                </button>
              )}
            </div>
          </div>
          {editingMem ? (
            <textarea
              style={{ width: '100%', minHeight: 420, fontFamily: 'monospace', fontSize: 13 }}
              value={memory}
              onChange={e => setMemory(e.target.value)}
            />
          ) : (
            <pre className="code">{memory || '(暂无内容)'}</pre>
          )}
        </div>
      )}

      {tab === 'prompt' && (
        <div className="card">
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
            <h3 style={{ margin: 0 }}>memory_prompt.txt</h3>
            <div className="row" style={{ gap: 6 }}>
              {editingPrompt ? (
                <>
                  <button className="ghost" onClick={() => { setEditingPrompt(false); refresh(); }}>取消</button>
                  <button className="primary" onClick={savePrompt}>保存</button>
                </>
              ) : (
                <button className="ghost" onClick={() => setEditingPrompt(true)}>
                  <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>edit</span>
                  编辑
                </button>
              )}
            </div>
          </div>
          {editingPrompt ? (
            <textarea
              style={{ width: '100%', minHeight: 420, fontFamily: 'monospace', fontSize: 13 }}
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
            />
          ) : (
            <pre className="code">{prompt || '(暂无内容)'}</pre>
          )}
        </div>
      )}

      {tab === 'log' && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>构建日志</h3>
          {log.length === 0 ? (
            <p className="muted">无日志。点击上方按钮开始构建。</p>
          ) : (
            <pre className="code" style={{ maxHeight: 500 }}>{log.join('\n')}</pre>
          )}
        </div>
      )}

      {tab === 'versions' && (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="folder-row head" style={{ gridTemplateColumns: '80px 180px 80px 1fr 120px' }}>
            <div>版本</div>
            <div>创建时间</div>
            <div>来源</div>
            <div>摘要</div>
            <div></div>
          </div>
          {versions.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center' }} className="muted">暂无版本记录</div>
          ) : versions.map(v => (
            <div key={v.id} style={{ borderBottom: '1px solid #211f24' }}>
              <div
                className="folder-row"
                style={{ gridTemplateColumns: '80px 180px 80px 1fr 120px' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span className="mi" style={{ fontSize: 14, color: '#cfbcff' }}>bookmark</span>
                  <code className="mono" style={{ color: '#cfbcff' }}>{v.id}</code>
                </div>
                <div style={{ color: '#b5afbd', fontSize: 12.5 }}>{formatTimeStr(v.created_at)}</div>
                <div>
                  <span className="tag" style={{
                    background: v.source === 'ai_build' ? 'rgba(103,80,164,0.15)' : 'rgba(231,195,101,0.15)',
                    color: v.source === 'ai_build' ? '#cfbcff' : '#e7c365',
                  }}>
                    {v.source === 'ai_build' ? 'AI构建' : v.source === 'user_edit' ? '用户编辑' : 'AI补充'}
                  </span>
                </div>
                <div style={{ color: '#948e9c', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {v.summary}
                </div>
                <div style={{ textAlign: 'right', display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                  <button className="ghost" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => viewVersion(v.id)}>
                    查看
                  </button>
                  <button className="ghost" style={{ padding: '4px 8px', fontSize: 11, color: '#e7c365' }} onClick={() => restoreVersion(v.id)}>
                    恢复
                  </button>
                </div>
              </div>
              {previewVersion?.id === v.id && (
                <div style={{ padding: '12px 16px 16px 56px', background: 'rgba(15,13,19,0.3)' }}>
                  <pre className="code" style={{ maxHeight: 320 }}>{previewVersion.memory_md || '(空)'}</pre>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === 'builds' && (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="folder-row head" style={{ gridTemplateColumns: '60px 170px 80px 60px 1fr 120px' }}>
            <div>ID</div>
            <div>开始时间</div>
            <div>耗时</div>
            <div>类型</div>
            <div>摘要</div>
            <div></div>
          </div>
          {builds.length === 0 ? (
            <div style={{ padding: 32, textAlign: 'center' }} className="muted">暂无构建记录</div>
          ) : builds.map(b => (
            <div key={b.id} style={{ borderBottom: '1px solid #211f24' }}>
              <div
                className="folder-row"
                style={{ gridTemplateColumns: '60px 170px 80px 60px 1fr 120px' }}
              >
                <div>
                  <span className="mi" style={{
                    fontSize: 14,
                    color: b.status === 'completed' ? '#7fd9a8' : b.status === 'running' ? '#e7c365' : '#ffb4ab'
                  }}>
                    {b.status === 'completed' ? 'check_circle' : b.status === 'running' ? 'autorenew' : 'cancel'}
                  </span>
                  <span style={{ marginLeft: 4 }}>{b.id}</span>
                </div>
                <div style={{ color: '#b5afbd', fontSize: 12.5 }}>{formatTimeStr(b.started_at)}</div>
                <div style={{ color: '#948e9c' }}>{elapsed(b.started_at, b.finished_at)}</div>
                <div>
                  <span className="tag mono" style={{
                    background: b.type === 'full' ? 'rgba(231,195,101,0.12)' : 'rgba(103,188,164,0.12)',
                    color: b.type === 'full' ? '#e7c365' : '#7fd9a8'
                  }}>
                    {b.type === 'full' ? 'FULL' : 'INCR'}
                  </span>
                </div>
                <div style={{ color: '#948e9c', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {b.summary}
                  {b.version_id && (
                    <span style={{ marginLeft: 6, fontSize: 10, color: '#cfbcff' }}>→ {b.version_id}</span>
                  )}
                </div>
                <div style={{ textAlign: 'right', display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                  <button className="ghost" style={{ padding: '4px 8px', fontSize: 11 }} onClick={() => viewBuild(b.id)}>
                    详情
                  </button>
                  {b.status === 'completed' && b.version_id && (
                    <button
                      className="ghost"
                      style={{ padding: '4px 8px', fontSize: 11, color: '#e7c365' }}
                      onClick={() => restoreFromBuild(b.id)}
                      title={`恢复到 ${b.version_id}`}
                    >
                      恢复
                    </button>
                  )}
                </div>
              </div>
              {previewBuild?.id === b.id && (
                <div style={{ padding: '12px 16px 16px 48px', background: 'rgba(15,13,19,0.3)' }}>
                  <pre className="code" style={{ maxHeight: 400, fontSize: 11 }}>
                    {(previewBuild.log || []).join('\n') || '（无详细日志）'}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {tab === 'inferred' && (
        <div className="card" style={{ padding: 16 }}>
          <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
            <div>
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="mi" style={{ color: '#cfbcff' }}>auto_awesome</span>
                历史反哺候选
              </h3>
              <div className="muted" style={{ marginTop: 4, fontSize: 12 }}>
                来自历史用例 / XMind 反推的隐性规则。高置信度（≥0.9）自动通过入库，低置信度需人工审核。
              </div>
            </div>
            <div className="row" style={{ gap: 6 }}>
              {['pending', 'auto_accepted', 'accepted', 'rejected', 'all'].map(s => (
                <button
                  key={s}
                  className={inferredFilter === s ? 'primary' : 'ghost'}
                  style={{ padding: '4px 10px', fontSize: 12 }}
                  onClick={() => setInferredFilter(s)}
                >
                  {{ pending: '待审', auto_accepted: 'AI自动通过', accepted: '已通过', rejected: '已拒绝', all: '全部' }[s]}
                </button>
              ))}
              <button className="ghost" style={{ padding: '4px 10px', fontSize: 12 }} onClick={refreshInferred}>
                <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>refresh</span>
                刷新
              </button>
            </div>
          </div>
          {inferredErr && <div className="err" style={{ marginBottom: 8 }}>{inferredErr}</div>}
          
          {/* 批量操作按钮 */}
          {inferred.length > 0 && inferredFilter === 'pending' && (
            <div className="row" style={{ gap: 8, marginBottom: 12, alignItems: 'center' }}>
              <button
                className="ghost"
                style={{ padding: '4px 12px', fontSize: 12 }}
                onClick={toggleSelectAll}
              >
                <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>
                  {selectedInferred.size === getCurrentPageItems().length && getCurrentPageItems().length > 0 ? 'check_box' : 'check_box_outline_blank'}
                </span>
                {selectedInferred.size === getCurrentPageItems().length && getCurrentPageItems().length > 0 ? '取消全选' : '全选当前页'}
              </button>
              
              {selectedInferred.size > 0 && (
                <>
                  <span style={{ fontSize: 12, color: '#948e9c' }}>已选择 {selectedInferred.size} 项</span>
                  <button
                    className="primary"
                    style={{ padding: '4px 12px', fontSize: 12 }}
                    onClick={() => batchReviewInferred('accept')}
                  >
                    <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>check</span>
                    批量通过
                  </button>
                  <button
                    className="ghost"
                    style={{ padding: '4px 12px', fontSize: 12, color: '#ffb4ab' }}
                    onClick={() => batchReviewInferred('reject')}
                  >
                    <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>close</span>
                    批量拒绝
                  </button>
                </>
              )}
            </div>
          )}
          
          {inferred.length === 0 ? (
            <div className="muted" style={{ padding: 28, textAlign: 'center' }}>
              暂无{ { pending: '待审', auto_accepted: 'AI自动通过', accepted: '已通过', rejected: '已拒绝', all: '' }[inferredFilter] }候选。先到「文件夹 / 历史用例」运行五阶段分析。
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {getCurrentPageItems().map(it => (
                <div key={it.inferred_id} style={{
                  border: `1px solid ${it.review_status === 'auto_accepted' ? 'rgba(127,217,168,0.35)' : '#2b292f'}`, borderRadius: 8, padding: 12,
                  background: it.review_status === 'auto_accepted' ? 'rgba(127,217,168,0.06)' : 'rgba(15,13,19,0.3)',
                }}>
                  <div className="row" style={{ justifyContent: 'space-between', marginBottom: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      {it.review_status === 'pending' && (
                        <input
                          type="checkbox"
                          checked={selectedInferred.has(it.inferred_id)}
                          onChange={() => toggleSelectInferred(it.inferred_id)}
                          style={{ marginRight: 4 }}
                        />
                      )}
                      <span className="tag info mono">{it.type}</span>
                      <span className="tag mono">{it.module || '(无模块)'}</span>
                      <span
                        className="tag"
                        style={{
                          color: it.confidence >= 0.9 ? '#7fd9a8' : it.confidence >= 0.6 ? '#e7c365' : '#ffb4ab',
                          background: it.auto_accepted ? 'rgba(127,217,168,0.15)' : undefined,
                        }}
                      >
                        conf {(it.confidence ?? 0).toFixed(2)}
                      </span>
                      {it.review_status === 'auto_accepted' && <span className="tag" style={{ background: 'rgba(127,217,168,0.18)', color: '#7fd9a8' }}><span className="mi" style={{ fontSize: 12, verticalAlign: -2, marginRight: 2 }}>auto_awesome</span>AI自动通过</span>}
                      {it.review_status === 'accepted' && <span className="tag ok">已通过</span>}
                      {it.review_status === 'rejected' && <span className="tag err">已拒绝</span>}
                      {it.review_status === 'pending' && <span className="tag warn">待审</span>}
                      {it.aggregated_from?.length > 1 && (
                        <span className="tag" style={{ background: 'rgba(207,188,255,0.12)', color: '#cfbcff', cursor: 'pointer' }} onClick={() => toggleSourceExpand(it.inferred_id)}>
                          <span className="mi" style={{ fontSize: 12, verticalAlign: -2, marginRight: 2 }}>{expandedSources.has(it.inferred_id) ? 'unfold_less' : 'unfold_more'}</span>
                          {it.aggregated_from.length} 源聚合
                        </span>
                      )}
                    </div>
                    <div className="muted mono" style={{ fontSize: 11 }}>{it.inferred_id}</div>
                  </div>

                  {/* 编辑模式 */}
                  {editingInferredId === it.inferred_id ? (
                    <div style={{ marginBottom: 8 }}>
                      <textarea
                        style={{ width: '100%', minHeight: 80, fontSize: 13, fontFamily: 'inherit', background: '#2b292f', color: '#e6e0e9', border: '1px solid #494551', borderRadius: 6, padding: 8 }}
                        value={editingContent}
                        onChange={e => setEditingContent(e.target.value)}
                      />
                      <div className="row" style={{ gap: 6, marginTop: 6, justifyContent: 'flex-end' }}>
                        <button className="ghost" style={{ padding: '3px 10px', fontSize: 12 }} onClick={cancelEditInferred}>取消</button>
                        <button className="primary" style={{ padding: '3px 10px', fontSize: 12 }} onClick={() => saveEditInferred(it)}>保存</button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ fontSize: 13, color: '#e6e0e9', marginBottom: 6 }}>{it.content}</div>
                  )}

                  {it.aliases?.length > 0 && (
                    <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                      别名：{it.aliases.join(' / ')}
                    </div>
                  )}
                  {it.reasoning && (
                    <div className="muted" style={{ fontSize: 11.5, lineHeight: 1.6, marginBottom: 6 }}>
                      <span className="mi" style={{ fontSize: 12, verticalAlign: -2, marginRight: 4 }}>psychology</span>
                      推理：{it.reasoning}
                    </div>
                  )}
                  {it.source_summary && (
                    <div style={{ fontSize: 11.5, lineHeight: 1.6, marginBottom: 6, color: '#cfbcff', background: 'rgba(207,188,255,0.06)', padding: '6px 10px', borderRadius: 6 }}>
                      <span className="mi" style={{ fontSize: 12, verticalAlign: -2, marginRight: 4 }}>summarize</span>
                      AI 总结依据：{it.source_summary}
                    </div>
                  )}

                  {/* 聚合源展开 */}
                  {expandedSources.has(it.inferred_id) && it.aggregated_from?.length > 0 && (
                    <div style={{ fontSize: 11, color: '#948e9c', marginBottom: 6, background: 'rgba(207,188,255,0.04)', padding: '6px 10px', borderRadius: 6 }}>
                      <div style={{ color: '#cfbcff', marginBottom: 4, fontWeight: 500 }}>聚合自以下 {it.aggregated_from.length} 个来源：</div>
                      {it.aggregated_from.map((src, idx) => (
                        <div key={idx} className="mono" style={{ marginBottom: 2, paddingLeft: 8 }}>
                          {src.kind === 'case' ? '📋' : '🧠'} {src.file}
                          {src.case_id && <> · {src.case_id}{src.case_row ? ` (行${src.case_row})` : ''}</>}
                          {src.node_path?.length > 0 && <> · {src.node_path.join(' › ')}</>}
                        </div>
                      ))}
                    </div>
                  )}

                  <div className="muted mono" style={{ fontSize: 11 }}>
                    源：{it.source?.kind === 'case' ? '用例' : 'XMind'} · {it.source?.file}
                    {it.source?.case_id && <> · {it.source.case_id} (行 {it.source.case_row})</>}
                    {it.source?.node_path?.length > 0 && <> · {it.source.node_path.join(' › ')}</>}
                  </div>

                  {/* 操作按钮行 */}
                  <div className="row" style={{ gap: 6, marginTop: 10, justifyContent: 'flex-end' }}>
                    {it.review_status === 'pending' && (
                      <>
                        <button
                          className="ghost"
                          style={{ padding: '4px 12px', fontSize: 12, color: '#ffb4ab' }}
                          onClick={() => reviewInferred(it, 'reject')}
                        >
                          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>close</span>
                          拒绝
                        </button>
                        <button
                          className="primary"
                          style={{ padding: '4px 12px', fontSize: 12 }}
                          onClick={() => reviewInferred(it, 'accept')}
                        >
                          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>check</span>
                          通过
                        </button>
                      </>
                    )}
                    {it.review_status === 'auto_accepted' && (
                      <>
                        <button
                          className="ghost"
                          style={{ padding: '4px 12px', fontSize: 12, color: '#e7c365' }}
                          onClick={() => revokeAutoAccepted(it)}
                          title="撤销自动通过，恢复为待审核状态"
                        >
                          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>undo</span>
                          撤销
                        </button>
                        <button
                          className="ghost"
                          style={{ padding: '4px 12px', fontSize: 12 }}
                          onClick={() => startEditInferred(it)}
                        >
                          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>edit</span>
                          修改
                        </button>
                      </>
                    )}
                    {it.review_status === 'accepted' && editingInferredId !== it.inferred_id && (
                      <button
                        className="ghost"
                        style={{ padding: '4px 12px', fontSize: 12 }}
                        onClick={() => startEditInferred(it)}
                      >
                        <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 2 }}>edit</span>
                        二次修改
                      </button>
                    )}
                  </div>

                  {it.reviewed_at && (
                    <div className="muted mono" style={{ fontSize: 10, marginTop: 6 }}>
                      审核于 {formatTimeStr(it.reviewed_at)}{it.reviewed_by ? ` · ${it.reviewed_by}` : ''}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          
          {/* 分页控件 */}
          {inferred.length > 0 && (
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginTop: 16, paddingTop: 12, borderTop: '1px solid #2b292f' }}>
              <div className="muted" style={{ fontSize: 12 }}>
                显示 {((currentPage - 1) * pageSize) + 1}-{Math.min(currentPage * pageSize, inferred.length)} 条，共 {inferred.length} 条
              </div>
              <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                <select
                  value={pageSize}
                  onChange={(e) => {
                    setPageSize(Number(e.target.value));
                    setCurrentPage(1);
                  }}
                  style={{
                    background: '#2b292f',
                    color: '#e6e0e9',
                    border: '1px solid #494551',
                    borderRadius: 4,
                    padding: '4px 8px',
                    fontSize: 12
                  }}
                >
                  <option value={5}>5条/页</option>
                  <option value={10}>10条/页</option>
                  <option value={20}>20条/页</option>
                  <option value={50}>50条/页</option>
                </select>
                
                <button
                  className="ghost"
                  style={{ padding: '4px 8px', fontSize: 12 }}
                  onClick={() => goToPage(currentPage - 1)}
                  disabled={currentPage <= 1}
                >
                  <span className="mi" style={{ fontSize: 14, verticalAlign: -2 }}>chevron_left</span>
                </button>
                
                <span style={{ fontSize: 12, minWidth: 60, textAlign: 'center' }}>
                  {currentPage} / {totalPages || 1}
                </span>
                
                <button
                  className="ghost"
                  style={{ padding: '4px 8px', fontSize: 12 }}
                  onClick={() => goToPage(currentPage + 1)}
                  disabled={currentPage >= totalPages}
                >
                  <span className="mi" style={{ fontSize: 14, verticalAlign: -2 }}>chevron_right</span>
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}