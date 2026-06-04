import React, { useEffect, useMemo, useState, useRef } from 'react';
import { api } from '../api.js';
import { useProject } from '../store.js';
import InferredReviewPanel from '../components/InferredReviewPanel.jsx';
import useInferredReview from '../hooks/useInferredReview.js';
import AiModelSelect, { useScopedLLM } from '../components/AiModelSelect.jsx';

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
  const [llm, selectedModel, setSelectedModel, defaultModel] = useScopedLLM('memory-build');
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

  const inferredReview = useInferredReview(project);
  
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
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
            <AiModelSelect
              value={selectedModel}
              onChange={setSelectedModel}
              defaultModel={defaultModel}
              disabled={busy || !project || cooldown}
              title="选择构建 AI 记忆模型"
            />
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

      {tab === 'inferred' && <InferredReviewPanel {...inferredReview} />}
    </div>
  );
}
