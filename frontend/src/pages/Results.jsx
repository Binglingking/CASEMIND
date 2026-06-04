import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import TestCaseTable from '../components/TestCaseTable.jsx';
import XMindTree from '../components/XMindTree.jsx';
import BatchResultCard from '../components/BatchResultCard.jsx';
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
  const icon = item.kind === 'testcase' ? 'fact_check' : item.kind === 'xmind' ? 'account_tree' : 'picture_as_pdf';
  const iconColor = item.kind === 'testcase' ? '#cfbcff' : item.kind === 'xmind' ? '#e7c365' : '#ffb4ab';
  const typeLabel = item.kind === 'testcase' ? 'TESTCASE' : item.kind === 'xmind' ? 'XMIND' : 'REQ PDF';

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
      await api.downloadOutput(project, item.kind, item.name);
    } catch (ex) { alert(String(ex.message || ex)); }
  }

  async function handleExportExcel(e) {
    e.stopPropagation();
    try {
      await api.exportOutputExcel(project, item.kind, item.name);
    } catch (err) {
      console.error('Excel导出错误:', err);
      alert(`导出失败: ${err.message || err}`);
    }
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
          {typeLabel}
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
        {item.kind === 'req_analysis' && (
          <button className="icon-btn" onClick={handleDownloadMarkdown} title="下载 PDF">
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
  const [batches, setBatches] = useState([]);
  const [err, setErr] = useState('');
  const [filter, setFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [previewItem, setPreviewItem] = useState(null);
  const [previewContent, setPreviewContent] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewErr, setPreviewErr] = useState('');
  const [openBatch, setOpenBatch] = useState(null);  // full manifest of the opened batch folder
  const [batchPreview, setBatchPreview] = useState(null);  // {name, content, kind}
  const location = useLocation();
  const navigate = useNavigate();

  async function refresh() {
    if (!project) { setItems([]); setBatches([]); return; }
    setErr('');
    try {
      const [r1, r2] = await Promise.all([
        api.listOutputs(project),
        api.batchList(project).catch(() => ({ batches: [] })),
      ]);
      setItems(r1.outputs || []);
      setBatches(r2.batches || []);
    } catch (e) { setErr(String(e.message || e)); }
  }

  useEffect(() => { refresh(); }, [project]);
  useEffect(() => { setPage(1); }, [filter, project, pageSize]);

  // Auto-open preview when ?kind=&name= present in URL
  useEffect(() => {
    if (!project || items.length === 0) return;
    const params = new URLSearchParams(location.search);
    const kind = params.get('kind');
    const name = params.get('name');
    if (!kind || !name) return;
    const target = items.find(it => it.kind === kind && it.name === name);
    if (target) {
      setFilter(kind);
      openPreview(target);
      navigate('/results', { replace: true });
    }
  }, [items, project, location.search]);

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
  const reqCount = items.filter(i => i.kind === 'req_analysis').length;
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageStart = filtered.length === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const pageEnd = Math.min(currentPage * pageSize, filtered.length);
  const paged = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="page-title">输出与导出</div>
          <div className="page-sub">浏览、预览、重命名、下载所有生成结果。</div>
        </div>
        <div className="mode-tabs">
          <button className={filter === 'all' ? 'active' : ''} onClick={() => { setFilter('all'); setOpenBatch(null); }}>
            全部 ({items.length})
          </button>
          <button className={filter === 'testcase' ? 'active' : ''} onClick={() => { setFilter('testcase'); setOpenBatch(null); }}>
            测试用例 ({tcCount})
          </button>
          <button className={filter === 'xmind' ? 'active' : ''} onClick={() => { setFilter('xmind'); setOpenBatch(null); }}>
            XMind ({xmCount})
          </button>
          <button className={filter === 'req_analysis' ? 'active' : ''} onClick={() => { setFilter('req_analysis'); setOpenBatch(null); }}>
            需求分析 ({reqCount})
          </button>
          <button className={filter === 'batch' ? 'active' : ''} onClick={() => { setFilter('batch'); setOpenBatch(null); }}>
            批次文件夹 ({batches.length})
          </button>
        </div>
      </div>

      {err && <p className="err">{err}</p>}

      {filter === 'batch' ? (
        openBatch ? (
          <div className="card" style={{ padding: 16 }}>
            <div className="row" style={{ justifyContent: 'space-between', marginBottom: 12 }}>
              <button className="ghost" onClick={() => setOpenBatch(null)} style={{ padding: '4px 12px', fontSize: 12 }}>
                <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>arrow_back</span>
                返回批次列表
              </button>
              <button
                className="ghost"
                style={{ color: '#ffb4ab', padding: '4px 12px', fontSize: 12 }}
                onClick={async () => {
                  if (!confirm(`删除批次「${openBatch.batch_name}」及其所有文件？`)) return;
                  try {
                    await api.batchDelete(project, openBatch.batch_id);
                    setOpenBatch(null);
                    refresh();
                  } catch (e) { alert(String(e.message || e)); }
                }}
              >
                <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>delete</span>
                删除整个批次
              </button>
            </div>
            <BatchResultCard
              manifest={openBatch}
              onDownload={async (fmt) => {
                const fname = fmt === 'zip'
                  ? `${openBatch.batch_name}.zip`
                  : (openBatch.kind === 'testcase' ? `${openBatch.batch_name}.xlsx` : `${openBatch.batch_name}.md`);
                try { await api.batchDownload(project, openBatch.batch_id, fmt, fname); }
                catch (e) { alert(String(e.message || e)); }
              }}
              onPreviewUnit={async (unit) => {
                try {
                  const r = await api.batchGetUnit(project, openBatch.batch_id, unit.unit_id);
                  if (r.missing) { alert('该模块文件不存在'); return; }
                  setBatchPreview({
                    name: unit.output_file || `${unit.unit_id}`,
                    content: r.content || '',
                    kind: openBatch.kind,
                  });
                } catch (e) { alert(String(e.message || e)); }
              }}
            />
          </div>
        ) : batches.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: 48 }}>
            <span className="mi" style={{ fontSize: 40, color: '#494551' }}>folder_open</span>
            <p className="muted" style={{ marginTop: 8 }}>
              暂无批次文件夹 — 在「AI 对话」中选择「测试用例」或「思维导图」模式即可创建。
            </p>
          </div>
        ) : (
          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div className="folder-row head" style={{ gridTemplateColumns: '1fr 100px 100px 100px 100px 160px' }}>
              <div>批次名</div>
              <div>类型</div>
              <div>模块</div>
              <div>状态</div>
              <div>更新</div>
              <div></div>
            </div>
            {batches.map(b => (
              <div
                key={b.batch_id}
                className="folder-row"
                style={{
                  gridTemplateColumns: '1fr 100px 100px 100px 100px 160px',
                  cursor: 'pointer', borderBottom: '1px solid #211f24',
                }}
                onClick={async () => {
                  try {
                    const m = await api.batchGet(project, b.batch_id);
                    setOpenBatch(m);
                  } catch (e) { alert(String(e.message || e)); }
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                  <span className="mi" style={{ color: '#cfbcff' }}>folder</span>
                  <span style={{ fontSize: 13, color: '#e6e0e9', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {b.batch_name}
                  </span>
                </div>
                <div>
                  <span className="tag info mono">{b.kind === 'testcase' ? 'TESTCASE' : 'XMIND'}</span>
                </div>
                <div style={{ color: '#d8d3de', fontSize: 12.5 }}>
                  {b.done_count}/{b.unit_count}
                </div>
                <div style={{ fontSize: 12.5, color: b.status === 'done' ? '#7fd17f' : b.status === 'failed' ? '#e76f6f' : '#cfbcff' }}>
                  {{ draft: '草稿', running: '运行中', done: '完成', partial: '部分完成', failed: '失败' }[b.status] || b.status}
                </div>
                <div style={{ color: '#b5afbd', fontSize: 12 }}>
                  {b.updated_at ? new Date(b.updated_at).toLocaleString() : '-'}
                </div>
                <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 2 }}>
                  <button
                    className="icon-btn"
                    title={b.kind === 'testcase' ? '下载合并 Excel' : '下载合并 MD'}
                    onClick={async (e) => {
                      e.stopPropagation();
                      const fname = b.kind === 'testcase' ? `${b.batch_name}.xlsx` : `${b.batch_name}.md`;
                      try { await api.batchDownload(project, b.batch_id, 'merged', fname); }
                      catch (ex) { alert(String(ex.message || ex)); }
                    }}
                  >
                    <span className="mi" style={{ fontSize: 14 }}>{b.kind === 'testcase' ? 'grid_on' : 'description'}</span>
                  </button>
                  <button
                    className="icon-btn"
                    title="下载 zip"
                    onClick={async (e) => {
                      e.stopPropagation();
                      try { await api.batchDownload(project, b.batch_id, 'zip', `${b.batch_name}.zip`); }
                      catch (ex) { alert(String(ex.message || ex)); }
                    }}
                  >
                    <span className="mi" style={{ fontSize: 14 }}>archive</span>
                  </button>
                  <button
                    className="icon-btn"
                    title="删除批次"
                    style={{ color: '#ffb4ab' }}
                    onClick={async (e) => {
                      e.stopPropagation();
                      if (!confirm(`删除批次 ${b.batch_name}？`)) return;
                      try { await api.batchDelete(project, b.batch_id); refresh(); }
                      catch (ex) { alert(String(ex.message || ex)); }
                    }}
                  >
                    <span className="mi" style={{ fontSize: 14 }}>close</span>
                  </button>
                </div>
              </div>
            ))}
          </div>
        )
      ) : filtered.length === 0 ? (
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
          {paged.map(item => (
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
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
          }}>
            <span>
              合计 {items.length} 个文件 · 测试用例 {tcCount} · XMind {xmCount} · 需求分析 {reqCount}
              {filtered.length > 0 && <> · 当前 {pageStart}-{pageEnd} / {filtered.length}</>}
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>每页</span>
              <select
                value={pageSize}
                onChange={e => setPageSize(Number(e.target.value))}
                style={{ width: 72 }}
              >
                {[10, 20, 50].map(n => <option key={n} value={n}>{n}</option>)}
              </select>
              <button className="ghost" disabled={currentPage <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>
                上一页
              </button>
              <span>{currentPage} / {totalPages}</span>
              <button className="ghost" disabled={currentPage >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>
                下一页
              </button>
            </span>
          </div>
        </div>
      )}

      {batchPreview && (() => {
        let parsedCases = null;
        if (batchPreview.kind === 'testcase') {
          try {
            const obj = JSON.parse(batchPreview.content || '{}');
            parsedCases = Array.isArray(obj) ? obj : (obj.cases || []);
          } catch { parsedCases = null; }
        }
        return (
          <div
            style={{
              position: 'fixed', inset: 0, zIndex: 1100,
              background: 'rgba(0,0,0,0.78)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
            }}
            onClick={() => setBatchPreview(null)}
          >
            <div
              className="card"
              onClick={e => e.stopPropagation()}
              style={{ padding: 16, width: 1100, maxWidth: '92vw', maxHeight: '88vh', display: 'flex', flexDirection: 'column', gap: 10 }}
            >
              <div className="row" style={{ justifyContent: 'space-between' }}>
                <div style={{ fontWeight: 600 }}>
                  <span className="mi" style={{ marginRight: 6, verticalAlign: -3, color: batchPreview.kind === 'testcase' ? '#cfbcff' : '#e7c365' }}>
                    {batchPreview.kind === 'testcase' ? 'fact_check' : 'account_tree'}
                  </span>
                  {batchPreview.name}
                  {batchPreview.kind === 'testcase' && parsedCases && (
                    <span className="muted" style={{ fontSize: 12, marginLeft: 8 }}>
                      · {parsedCases.length} 条用例
                    </span>
                  )}
                </div>
                <button className="icon-btn" onClick={() => setBatchPreview(null)} title="关闭">
                  <span className="mi">close</span>
                </button>
              </div>
              <div style={{ flex: 1, overflow: 'auto', padding: '4px 2px' }}>
                {batchPreview.kind === 'testcase' && parsedCases && (
                  <TestCaseTable cases={parsedCases} />
                )}
                {batchPreview.kind === 'testcase' && !parsedCases && (
                  <textarea
                    value={batchPreview.content} readOnly
                    style={{ width: '100%', minHeight: 400, fontFamily: 'monospace', fontSize: 12, background: 'rgba(20,16,28,0.7)' }}
                  />
                )}
                {batchPreview.kind === 'xmind' && (
                  <XMindTree markdown={batchPreview.content || ''} />
                )}
              </div>
            </div>
          </div>
        );
      })()}

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
              <span className="mi" style={{ color: previewItem.kind === 'testcase' ? '#cfbcff' : previewItem.kind === 'xmind' ? '#e7c365' : '#ffb4ab' }}>
                {previewItem.kind === 'testcase' ? 'fact_check' : previewItem.kind === 'xmind' ? 'account_tree' : 'picture_as_pdf'}
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
                  {previewItem.kind === 'req_analysis' && (
                    <div style={{ textAlign: 'center', padding: 32 }}>
                      <span className="mi" style={{ fontSize: 42, color: '#ffb4ab' }}>picture_as_pdf</span>
                      <h3 style={{ marginTop: 12, marginBottom: 8 }}>需求分析 PDF</h3>
                      <p className="muted" style={{ margin: 0 }}>
                        {formatSize(previewContent.size)} · {formatTime(previewContent.mtime)}
                      </p>
                      <button
                        className="primary"
                        style={{ marginTop: 16 }}
                        onClick={() => api.downloadOutput(project, 'req_analysis', previewItem.name).catch(e => alert(String(e.message || e)))}
                      >
                        <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>download</span>
                        下载 PDF
                      </button>
                    </div>
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
