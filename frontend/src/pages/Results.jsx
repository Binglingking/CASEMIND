import React, { useEffect, useState } from 'react';
import TestCaseTable from '../components/TestCaseTable.jsx';
import XMindTree from '../components/XMindTree.jsx';
import { useProject } from '../store.js';
import { api } from '../api.js';

function formatSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return '-';
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

function formatTime(ts) {
  const s = Number(ts);
  if (!Number.isFinite(s) || s <= 0) return '-';
  try { return new Date(s * 1000).toLocaleString(); } catch { return '-'; }
}

function OutputRow({ project, item, onRefresh, onPreview }) {
  const icon = item.kind === 'testcase' ? 'fact_check' : 'account_tree';
  const iconColor = item.kind === 'testcase' ? '#cfbcff' : '#e7c365';

  async function handleDownloadSource(e) {
    e.stopPropagation();
    const isMd = item.name.endsWith('.md');
    try {
      const data = await api.getOutputContent(project, item.kind, item.name);
      let blob, filename;
      if (isMd && data.markdown) {
        blob = new Blob([data.markdown], { type: 'text/markdown' });
        filename = item.name;
      } else {
        const payload = data.data || data;
        blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
        filename = item.name;
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } catch (ex) { alert(String(ex.message || ex)); }
  }

  async function handleDownloadMarkdown(e) {
    e.stopPropagation();
    try {
      const data = await api.getOutputContent(project, item.kind, item.name);
      if (!data?.markdown) { alert('没有 Markdown 内容'); return; }
      const blob = new Blob([data.markdown], { type: 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = item.name; a.click();
      URL.revokeObjectURL(url);
    } catch (ex) { alert(String(ex.message || ex)); }
  }

  function handleExportExcel(e) {
    e.stopPropagation();
    fetch('/api/outputs/export-excel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, kind: item.kind, filename: item.name }),
    })
      .then(resp => {
        if (!resp.ok) {
          return resp.text().then(text => {
            let msg = '导出失败';
            try { 
              const d = JSON.parse(text); 
              msg = d.detail || d.message || msg; 
            } catch (e) {
              msg = text || msg;
            }
            throw new Error(msg);
          });
        }
        return resp.blob();
      })
      .then(blob => {
        if (!blob || blob.size === 0) {
          throw new Error('导出的文件为空');
        }
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = item.name.replace(/\.[^.]+$/, '.xlsx');
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch(err => {
        console.error('Excel导出错误:', err);
        alert(`导出失败: ${err.message || err}`);
      });
  }

  async function handleRename(e) {
    e.stopPropagation();
    const newName = prompt('重命名文件', item.name);
    if (newName == null || newName.trim() === item.name) return;
    if (!newName.trim()) return;
    try {
      await api.renameOutput(project, item.kind, item.name, newName.trim());
      onRefresh();
    } catch (ex) { alert(String(ex.message || ex)); }
  }

  async function handleDelete(e) {
    e.stopPropagation();
    if (!confirm(`删除 ${item.name}？`)) return;
    try {
      await api.deleteOutput(project, item.kind, item.name);
      onRefresh();
    } catch (ex) { alert(String(ex.message || ex)); }
  }

  return (
    <div
      className="folder-row"
      style={{ cursor: 'pointer', gridTemplateColumns: '1fr 100px 180px 90px 160px', borderBottom: '1px solid #211f24' }}
      onClick={() => onPreview(item)}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <span className="mi" style={{ fontSize: 15, color: '#948e9c' }}>open_in_full</span>
        <span className="mi" style={{ color: iconColor }}>{icon}</span>
        <span style={{ fontSize: 13, color: '#e6e0e9', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {item.name}
        </span>
      </div>
      <div style={{ color: '#d8d3de' }}>{formatSize(item.size)}</div>
      <div style={{ color: '#b5afbd', fontSize: 12.5 }}>{formatTime(item.mtime)}</div>
      <div>
        <span className="tag info mono">
          {item.kind === 'testcase' ? 'TESTCASE' : 'XMIND'}
        </span>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 2 }}>
        {item.kind === 'testcase' && (
          <>
            <button className="icon-btn" onClick={handleDownloadSource} title={item.name.endsWith('.md') ? '下载 MD' : '下载 JSON'}>
              <span className="mi" style={{ fontSize: 14 }}>{item.name.endsWith('.md') ? 'description' : 'data_object'}</span>
            </button>
            <button className="icon-btn" onClick={handleExportExcel} title="导出 Excel">
              <span className="mi" style={{ fontSize: 14 }}>grid_on</span>
            </button>
          </>
        )}
        {item.kind === 'xmind' && (
          <button className="icon-btn" onClick={handleDownloadMarkdown} title="导出 Markdown">
            <span className="mi" style={{ fontSize: 14 }}>download</span>
          </button>
        )}
        <button className="icon-btn" onClick={handleRename} title="重命名">
          <span className="mi" style={{ fontSize: 14 }}>edit</span>
        </button>
        <button className="icon-btn" onClick={handleDelete} title="删除" style={{ color: '#ffb4ab' }}>
          <span className="mi" style={{ fontSize: 14 }}>close</span>
        </button>
      </div>
    </div>
  );
}

export default function Results() {
  const [project] = useProject();
  const [items, setItems] = useState([]);
  const [err, setErr] = useState('');
  const [filter, setFilter] = useState('all');
  const [previewItem, setPreviewItem] = useState(null);
  const [previewContent, setPreviewContent] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewErr, setPreviewErr] = useState('');

  async function refresh() {
    if (!project) { setItems([]); return; }
    setErr('');
    try {
      const r = await api.listOutputs(project);
      setItems(r.outputs || []);
    } catch (e) { setErr(String(e.message || e)); }
  }

  useEffect(() => { refresh(); }, [project]);

  async function openPreview(item) {
    setPreviewItem(item);
    setPreviewContent(null);
    setPreviewErr('');
    setPreviewLoading(true);
    try {
      const r = await api.getOutputContent(project, item.kind, item.name);
      setPreviewContent(r);
    } catch (e) { setPreviewErr(String(e.message || e)); }
    setPreviewLoading(false);
  }

  function closePreview() {
    setPreviewItem(null);
    setPreviewContent(null);
    setPreviewErr('');
  }

  useEffect(() => {
    if (!previewItem) return;
    const handler = (e) => { if (e.key === 'Escape') closePreview(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [previewItem]);

  const filtered = filter === 'all' ? items : items.filter(i => i.kind === filter);
  const tcCount = items.filter(i => i.kind === 'testcase').length;
  const xmCount = items.filter(i => i.kind === 'xmind').length;

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="page-title">输出与导出</div>
          <div className="page-sub">浏览、预览、重命名、下载所有生成结果。</div>
        </div>
        <div className="mode-tabs">
          <button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>
            全部 ({items.length})
          </button>
          <button className={filter === 'testcase' ? 'active' : ''} onClick={() => setFilter('testcase')}>
            测试用例 ({tcCount})
          </button>
          <button className={filter === 'xmind' ? 'active' : ''} onClick={() => setFilter('xmind')}>
            XMind ({xmCount})
          </button>
        </div>
      </div>

      {err && <p className="err">{err}</p>}

      {filtered.length === 0 ? (
        <div className="card" style={{ textAlign: 'center', padding: 48 }}>
          <span className="mi" style={{ fontSize: 40, color: '#494551' }}>inbox</span>
          <p className="muted" style={{ marginTop: 8 }}>
            {items.length === 0
              ? '还没有输出 — 去「AI 对话」选择模式生成。'
              : '当前筛选条件下没有文件。'}
          </p>
        </div>
      ) : (
        <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div className="folder-row head" style={{ gridTemplateColumns: '1fr 100px 180px 90px 160px' }}>
            <div>文件名</div>
            <div>大小</div>
            <div>生成时间</div>
            <div>类型</div>
            <div></div>
          </div>
          {filtered.map(item => (
            <OutputRow
              key={`${item.kind}/${item.name}`}
              project={project}
              item={item}
              onRefresh={refresh}
              onPreview={openPreview}
            />
          ))}
          <div style={{
            padding: '10px 16px', borderTop: '1px solid #211f24',
            color: '#948e9c', fontSize: 12, fontFamily: '"Space Grotesk", monospace',
          }}>
            合计 {items.length} 个文件 · 测试用例 {tcCount} · XMind {xmCount}
          </div>
        </div>
      )}

      {previewItem && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.72)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: 24,
          }}
          onClick={closePreview}
        >
          <div
            style={{
              background: '#1c1a21',
              borderRadius: 12,
              width: '90vw', maxWidth: 1200,
              maxHeight: '85vh',
              display: 'flex', flexDirection: 'column',
              overflow: 'hidden',
              border: '1px solid #2d2b33',
              boxShadow: '0 8px 40px rgba(0,0,0,0.6)',
            }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{
              display: 'flex', alignItems: 'center',
              padding: '14px 20px', borderBottom: '1px solid #2d2b33', gap: 8,
            }}>
              <span className="mi" style={{ color: previewItem.kind === 'testcase' ? '#cfbcff' : '#e7c365' }}>
                {previewItem.kind === 'testcase' ? 'fact_check' : 'account_tree'}
              </span>
              <span style={{
                flex: 1, fontWeight: 600, fontSize: 14, color: '#e6e0e9',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {previewItem.name}
              </span>
              <button className="icon-btn" onClick={closePreview} title="关闭 (Esc)">
                <span className="mi">close</span>
              </button>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
              {previewLoading && <p className="muted">加载中…</p>}
              {previewErr && <p className="err">{previewErr}</p>}
              {previewContent && !previewLoading && (
                <>
                  {previewItem.kind === 'testcase' && (
                    <TestCaseTable cases={previewContent.cases || previewContent.data?.cases || []} />
                  )}
                  {previewItem.kind === 'xmind' && (
                    <XMindTree markdown={previewContent.markdown || ''} />
                  )}
                  {previewContent.truncated && (
                    <p className="muted" style={{ marginTop: 8 }}>
                      <span className="tag warn">已截断</span>
                      文件过大，仅显示前 40000 字符。
                    </p>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
