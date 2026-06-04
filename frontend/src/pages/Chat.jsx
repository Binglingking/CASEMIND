import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api.js';
import {
  useProject, useChats, newChat, useLast, getStreamOutput,
} from '../store.js';
import AiModelSelect, { useScopedLLM } from '../components/AiModelSelect.jsx';
import UnitDraftCard from '../components/UnitDraftCard.jsx';
import BatchProgressCard from '../components/BatchProgressCard.jsx';
import BatchResultCard from '../components/BatchResultCard.jsx';
import TestCaseTable from '../components/TestCaseTable.jsx';
import XMindTree from '../components/XMindTree.jsx';

const MAX_IMAGE_SIZE_MB = 10;
const ALLOWED_IMAGE_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
const ALLOWED_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.gif', '.webp']);

function splitThinking(text) {
  if (!text) return { thinking: '', answer: '' };
  const re = /<think(?:ing)?>([\s\S]*?)<\/think(?:ing)?>/gi;
  let thinking = '';
  const answer = text.replace(re, (_, g1) => { thinking += (thinking ? '\n\n' : '') + g1.trim(); return ''; }).trim();
  return { thinking, answer };
}

// 需求分析问题的类型/严重程度中文标签与颜色
const TYPE_CONFIG = {
  conflict: { label: '矛盾冲突', color: '#e74c3c', bg: 'rgba(231,76,60,0.12)' },
  omission: { label: '遗漏缺失', color: '#e67e22', bg: 'rgba(230,126,34,0.12)' },
  logic_flaw: { label: '逻辑漏洞', color: '#c0392b', bg: 'rgba(192,57,43,0.12)' },
  risk: { label: '风险识别', color: '#e74c3c', bg: 'rgba(231,76,60,0.12)' },
  ambiguity: { label: '歧义模糊', color: '#8e44ad', bg: 'rgba(142,68,173,0.12)' },
  suggestion: { label: '建议改进', color: '#2980b9', bg: 'rgba(41,128,185,0.12)' },
};
const SEV_CONFIG = {
  high: { label: '高', color: '#e74c3c', bg: 'rgba(231,76,60,0.18)' },
  medium: { label: '中', color: '#e67e22', bg: 'rgba(230,126,34,0.18)' },
  low: { label: '低', color: '#2980b9', bg: 'rgba(41,128,185,0.18)' },
};

function ReqAnalysisCard({ data, onDownloadPDF }) {
  const { summary, statistics, issues } = data || {};
  const stats = statistics || {};
  const issueList = issues || [];
  const [downloading, setDownloading] = useState(false);

  async function handleDownload() {
    setDownloading(true);
    try {
      await onDownloadPDF();
    } catch (e) {
      alert('PDF 下载失败：' + (e.message || e));
    }
    setDownloading(false);
  }

  return (
    <div style={{ fontFamily: '"Space Grotesk", "Manrope", sans-serif' }}>
      {/* 头部 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 16, paddingBottom: 12,
        borderBottom: '1px solid #211f24',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span className="mi" style={{ fontSize: 22, color: '#cfbcff' }}>assignment</span>
          <span style={{ fontSize: 16, fontWeight: 700, color: '#e6e0e9' }}>需求分析报告</span>
        </div>
        <button
          className="primary"
          onClick={handleDownload}
          disabled={downloading}
          style={{ fontSize: 12, padding: '6px 14px' }}
        >
          <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>
            {downloading ? 'hourglass_top' : 'download'}
          </span>
          {downloading ? '生成中…' : '下载 PDF'}
        </button>
      </div>

      {/* 统计卡片 */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 20,
      }}>
        {['high', 'medium', 'low'].map(sev => {
          const cfg = SEV_CONFIG[sev];
          return (
            <div key={sev} style={{
              background: cfg.bg, borderRadius: 12, padding: '14px 12px',
              textAlign: 'center', border: `1px solid ${cfg.color}22`,
            }}>
              <div style={{ fontSize: 26, fontWeight: 700, color: cfg.color }}>
                {stats[sev] || 0}
              </div>
              <div style={{ fontSize: 11, color: cfg.color, marginTop: 2 }}>
                {sev === 'high' ? '高风险' : sev === 'medium' ? '中风险' : '低风险'}
              </div>
            </div>
          );
        })}
      </div>

      {/* 总体评价 */}
      {summary && (
        <div style={{
          background: 'rgba(207,188,255,0.06)', borderRadius: 12,
          padding: 14, marginBottom: 20, border: '1px solid #211f24',
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: '#cfbcff', marginBottom: 6 }}>
            总体评价
          </div>
          <div style={{ fontSize: 13, color: '#b5afbd', lineHeight: 1.7 }}>{summary}</div>
        </div>
      )}

      {/* 问题列表 */}
      {issueList.length > 0 && (
        <div>
          <div style={{
            fontSize: 13, fontWeight: 600, color: '#948e9c', marginBottom: 12,
          }}>
            发现 {issueList.length} 个问题
          </div>
          {issueList.map((issue, i) => {
            const tcfg = TYPE_CONFIG[issue.type] || TYPE_CONFIG.suggestion;
            const scfg = SEV_CONFIG[issue.severity] || SEV_CONFIG.low;
            return (
              <div key={issue.id || i} style={{
                background: '#1b1920', borderRadius: 12, padding: 16,
                marginBottom: 10, border: '1px solid #211f24',
                borderLeft: `3px solid ${scfg.color}`,
              }}>
                {/* 标题行 */}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10,
                  flexWrap: 'wrap',
                }}>
                  <span style={{
                    fontSize: 10, fontWeight: 600, color: '#494551',
                    fontFamily: '"Space Grotesk", monospace',
                  }}>
                    {issue.id || `ISS-${String(i + 1).padStart(3, '0')}`}
                  </span>
                  <span style={{
                    fontSize: 10, padding: '1px 8px', borderRadius: 4,
                    background: tcfg.bg, color: tcfg.color, fontWeight: 600,
                  }}>
                    {tcfg.label}
                  </span>
                  <span style={{
                    fontSize: 10, padding: '1px 8px', borderRadius: 4,
                    background: scfg.bg, color: scfg.color, fontWeight: 600,
                  }}>
                    {scfg.label}风险
                  </span>
                </div>
                {/* 标题 */}
                <div style={{
                  fontSize: 14, fontWeight: 700, color: scfg.color, marginBottom: 8,
                }}>
                  {issue.title || '（无标题）'}
                </div>
                {/* 详情 */}
                {issue.description && (
                  <InfoRow icon="subject" label="问题描述" text={issue.description} />
                )}
                {issue.location && (
                  <InfoRow icon="location_on" label="所在位置" text={issue.location} color="#948e9c" />
                )}
                {issue.impact && (
                  <InfoRow icon="warning" label="影响分析" text={issue.impact} color="#e7c365" />
                )}
                {issue.suggestion && (
                  <InfoRow icon="lightbulb" label="改进建议" text={issue.suggestion} color="#7fd9a8" italic />
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 无问题 */}
      {issueList.length === 0 && (
        <div style={{ textAlign: 'center', padding: 20, color: '#948e9c', fontSize: 13 }}>
          未发现明显问题，文档质量良好。
        </div>
      )}
    </div>
  );
}

function InfoRow({ icon, label, text, color = '#b5afbd', italic = false }) {
  return (
    <div style={{ marginBottom: 6, display: 'flex', gap: 6 }}>
      <span className="mi" style={{
        fontSize: 13, color: '#494551', marginTop: 1, flexShrink: 0,
      }}>{icon}</span>
      <div>
        <span style={{ fontSize: 10, color: '#494551', fontWeight: 600 }}>{label}</span>
        <div style={{
          fontSize: 12, color, lineHeight: 1.6, marginTop: 1,
          fontStyle: italic ? 'italic' : 'normal',
        }}>
          {text}
        </div>
      </div>
    </div>
  );
}

function ArtifactActions({ project, artifact }) {
  const navigate = useNavigate();
  if (!project || !artifact?.kind) return null;

  async function download() {
    try {
      if (artifact.kind === 'testcase') {
        await api.exportOutputExcel(project, 'testcase', artifact.filename);
      } else if (artifact.kind === 'xmind') {
        await api.downloadOutput(project, 'xmind', artifact.filename);
      } else if (artifact.kind === 'req_analysis') {
        await api.downloadOutput(project, 'req_analysis', artifact.pdfFilename || artifact.filename);
      }
    } catch (e) {
      alert('下载失败：' + (e.message || e));
    }
  }

  function openInLibrary() {
    const previewName = artifact.kind === 'req_analysis'
      ? (artifact.pdfFilename || artifact.filename)
      : artifact.filename;
    navigate(`/results?kind=${encodeURIComponent(artifact.kind)}&name=${encodeURIComponent(previewName)}`);
  }

  const label = artifact.kind === 'testcase'
    ? '下载 Excel'
    : artifact.kind === 'xmind'
      ? '下载 Markdown'
      : '下载 PDF';
  const icon = artifact.kind === 'testcase' ? 'grid_on' : artifact.kind === 'xmind' ? 'description' : 'picture_as_pdf';

  return (
    <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
      <button className="ghost" onClick={download} style={{ padding: '6px 12px', fontSize: 12 }}>
        <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>{icon}</span>
        {label}
      </button>
      <button className="ghost" onClick={openInLibrary} style={{ padding: '6px 12px', fontSize: 12 }}>
        <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>open_in_new</span>
        查看（AI 用例库）
      </button>
    </div>
  );
}

function ArtifactSummaryCard({ summary }) {
  if (!summary) return null;
  const { kind, count, modules, file, xmindStats } = summary;
  const titleMap = {
    testcase: '已生成测试用例',
    xmind: '已生成 XMind 思维导图',
    req_analysis: '已生成需求分析报告',
  };
  const iconMap = {
    testcase: 'fact_check',
    xmind: 'account_tree',
    req_analysis: 'assignment',
  };
  const colorMap = {
    testcase: '#cfbcff',
    xmind: '#e7c365',
    req_analysis: '#ffb4ab',
  };
  return (
    <div style={{
      background: 'rgba(207,188,255,0.06)', border: '1px solid #2d2b33',
      borderRadius: 12, padding: 14, marginBottom: 4,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span className="mi" style={{ fontSize: 20, color: colorMap[kind] || '#cfbcff' }}>{iconMap[kind] || 'description'}</span>
        <span style={{ fontSize: 14, fontWeight: 700, color: '#e6e0e9' }}>{titleMap[kind] || '已生成结果'}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 12.5, color: '#b5afbd' }}>
        {kind === 'testcase' && (
          <>
            <div><span className="muted">用例条数：</span><span style={{ color: '#e6e0e9' }}>{count ?? 0}</span></div>
            {modules?.length > 0 && (
              <div>
                <span className="muted">覆盖模块：</span>
                <span style={{ color: '#e6e0e9' }}>{modules.slice(0, 8).join('、')}{modules.length > 8 ? ` 等 ${modules.length} 个` : ''}</span>
              </div>
            )}
          </>
        )}
        {kind === 'xmind' && xmindStats && (
          <>
            {xmindStats.nodes != null && <div><span className="muted">节点数：</span><span style={{ color: '#e6e0e9' }}>{xmindStats.nodes}</span></div>}
            {xmindStats.depth != null && <div><span className="muted">最大深度：</span><span style={{ color: '#e6e0e9' }}>{xmindStats.depth}</span></div>}
          </>
        )}
        {file && (
          <div className="mono" style={{ fontSize: 11, color: '#948e9c', wordBreak: 'break-all' }}>
            <span className="muted">保存位置：</span>{file}
          </div>
        )}
      </div>
    </div>
  );
}

function smartTitle(userText, aiText = '') {
  const src = (userText || '').trim();
  if (!src) return '新对话';
  // strip leading greetings / fillers
  const stripped = src
    .replace(/^(请|帮我|麻烦|你好|hi|hello)[，,、:：\s]*/i, '')
    .replace(/[?？！!。.\n\r]+$/, '')
    .trim() || src;
  // first meaningful segment
  const seg = stripped.split(/[。.!！?？\n；;]/)[0] || stripped;
  const title = seg.slice(0, 18).trim();
  return title || src.slice(0, 18);
}

function CitationBlock({ sources }) {
  const [open, setOpen] = useState(false);
  if (!sources || sources.length === 0) return null;
  return (
    <div className="citations">
      <button className="ghost" onClick={() => setOpen(v => !v)} style={{ padding: '4px 10px', fontSize: 12 }}>
        <span className="mi" style={{ fontSize: 13, verticalAlign: -2, marginRight: 4 }}>
          {open ? 'expand_less' : 'expand_more'}
        </span>
        引用 {sources.length} 条
      </button>
      {open && (
        <ul>
          {sources.map((s, i) => (
            <li key={i}>
              <code className="mono">[{s.source} #{s.index}]</code>
              <span className="muted"> · score={Number(s.score).toFixed(3)}</span>
              {s.text && <div className="cite-text">{s.text}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ThinkingBlock({ text, elapsedMs, streaming }) {
  const [open, setOpen] = useState(false);
  if (!text && !streaming) return null;

  const steps = text
    ? text.split(/\n(?=\d+[\.\、\)])/g)
        .filter(s => s.trim())
        .map(s => s.trim())
    : [];

  const elapsed = elapsedMs
    ? `${(elapsedMs / 1000).toFixed(1)}s`
    : null;

  return (
    <details
      className="thinking-details"
      open={open || streaming}
      onToggle={(e) => setOpen(e.target.open)}
    >
      <summary className="thinking-summary">
        <span className="mi thinking-chevron">chevron_right</span>
        {streaming && <span className="thinking-pulse" />}
        {!streaming && <span className="thinking-dot" />}
        <span className="thinking-label">深度思考过程</span>
        {elapsed && <span className="thinking-time">已耗时 {elapsed}</span>}
        {streaming && !elapsed && <span className="thinking-time">进行中…</span>}
      </summary>
      <div className="thinking-body-v2">
        {steps.length <= 1
          ? <p>{text || '正在思考…'}</p>
          : steps.map((s, i) => <p key={i}>{s}</p>)
        }
      </div>
    </details>
  );
}

const CHAT_MODE_GROUPS = [
  { key: 'qa', label: '问答' },
  { key: 'chat', label: '普通问答' },
  { key: 'testcase', label: '生成测试用例' },
  { key: 'xmind', label: '生成 XMind' },
  { key: 'req_analysis', label: '需求分析' },
  { key: 'augment', label: '信息补充' },
];

const CHAT_MODE_KEYS = new Set(CHAT_MODE_GROUPS.map(g => g.key));

function normalizeChatMode(mode) {
  return CHAT_MODE_KEYS.has(mode) ? mode : 'qa';
}

function modeLabel(mode) {
  return CHAT_MODE_GROUPS.find(g => g.key === normalizeChatMode(mode))?.label || '问答';
}

function groupChatsByMode(chats) {
  const groups = Object.fromEntries(CHAT_MODE_GROUPS.map(g => [g.key, []]));
  chats.forEach(c => {
    groups[normalizeChatMode(c.mode)].push({ ...c, mode: normalizeChatMode(c.mode) });
  });
  return CHAT_MODE_GROUPS
    .map(g => ({
      ...g,
      items: groups[g.key].sort(
        (a, b) => ((b.updatedAt || b.createdAt || 0) - (a.updatedAt || a.createdAt || 0))
      ),
    }));
}

function filenameFromPath(path) {
  if (!path) return '';
  return String(path).split(/[\\/]/).pop();
}

function summaryFromResult(result) {
  if (!result?.mode) return null;
  const file = result.output_file || result.pdf_file || '';
  if (result.mode === 'testcase') {
    const cases = result.data?.cases || [];
    const modules = Array.from(new Set(cases.map(c => c.module || c.sub_item || '').filter(Boolean)));
    return { kind: 'testcase', count: cases.length, modules, file };
  }
  if (result.mode === 'xmind') {
    const md = result.markdown || '';
    const lines = md.split('\n').filter(l => /^\s*[-*#]/.test(l));
    const depth = md.split('\n').reduce((mx, l) => {
      const m = l.match(/^(#+)\s/);
      return m ? Math.max(mx, m[1].length) : mx;
    }, 0);
    return { kind: 'xmind', file, xmindStats: { nodes: lines.length, depth: depth || null } };
  }
  if (result.mode === 'req_analysis') {
    return { kind: 'req_analysis', file: result.pdf_file || file };
  }
  return null;
}

function artifactFromResult(result) {
  if (!result?.mode) return null;
  if (result.mode === 'testcase') {
    const filename = filenameFromPath(result.output_file) || result.output_filename;
    return filename ? { kind: 'testcase', filename, outputFile: result.output_file } : null;
  }
  if (result.mode === 'xmind') {
    const filename = filenameFromPath(result.output_file) || result.output_filename;
    return filename ? { kind: 'xmind', filename, outputFile: result.output_file } : null;
  }
  if (result.mode === 'req_analysis') {
    const pdfFilename = result.pdf_filename || filenameFromPath(result.pdf_file);
    return pdfFilename ? {
      kind: 'req_analysis',
      filename: pdfFilename,
      pdfFilename,
      outputFile: result.output_file,
      pdfFile: result.pdf_file,
    } : null;
  }
  return null;
}

function buildChatHistory(messages = []) {
  return messages
    .filter(m => ['user', 'assistant'].includes(m.role))
    .filter(m => !m._streaming)
    .map(m => {
      let content = String(m.content || '').trim();
      if (content.startsWith('__REQ_ANALYSIS__')) {
        content = '[需求分析结果已生成]';
      }
      return { role: m.role, content };
    })
    .filter(m => m.content)
    .slice(-12);
}

export default function Chat() {
  const [project] = useProject();
  const [llm, selectedModel, setSelectedModel, defaultModel] = useScopedLLM('chat');
  const [chats, activeId, chatsApi] = useChats(project);
  const [, setLast] = useLast(project);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [selectedMode, setSelectedMode] = useState('qa');
  // AI 分模块开关：仅在 testcase / xmind 模式下生效；默认关闭 → 走单次直生成
  const [aiSplitEnabled, setAiSplitEnabled] = useState(() => {
    try { return localStorage.getItem('casemind.aiSplit') === '1'; } catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem('casemind.aiSplit', aiSplitEnabled ? '1' : '0'); } catch {}
  }, [aiSplitEnabled]);
  const streamCtrlRef = useRef(null);
  const scrollRef = useRef(null);
  const textareaRef = useRef(null);
  const [error, setError] = useState(null);
  const [lastAnalysis, setLastAnalysis] = useState(null);  // 最近一次需求分析数据

  // 图片上传相关状态
  const [selectedImages, setSelectedImages] = useState([]); // [{id, file, previewUrl}]
  const [viewerImage, setViewerImage] = useState(null);     // {urls: [], index: 0} | null
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef(null);

  // @-mention multitiling data: legacy cases + legacy xmind + requirement docs + output items
  const [legacyCases, setLegacyCases] = useState([]);
  const [legacyXMind, setLegacyXMind] = useState([]);
  const [docFiles, setDocFiles] = useState([]);
  const [outputItems, setOutputItems] = useState([]);
  const [mentionState, setMentionState] = useState(null); // { query, start } | null

  useEffect(() => {
    if (!project) {
      setLegacyCases([]);
      setLegacyXMind([]);
      setDocFiles([]);
      setOutputItems([]);
      return;
    }
    api.legacyListCases(project)
      .then(r => setLegacyCases(r.files || []))
      .catch(e => {
        console.error('Failed to load legacy cases:', e);
        setLegacyCases([]);
      });
    api.legacyListXMind(project)
      .then(r => setLegacyXMind(r.files || []))
      .catch(e => {
        console.error('Failed to load legacy xmind:', e);
        setLegacyXMind([]);
      });
    api.listFolders(project)
      .then(r => {
        const folders = r.folders || [];
        return Promise.all(
          folders.map(f => api.listFolderFiles(project, f.path).catch(() => ({ files: [] })))
        );
      })
      .then(results => {
        const allFiles = results.flatMap(r => r.files || []);
        setDocFiles(allFiles);
      })
      .catch(e => {
        console.error('Failed to load doc files:', e);
        setDocFiles([]);
      });
    api.listOutputs(project)
      .then(r => setOutputItems(r.outputs || []))
      .catch(e => {
        console.error('Failed to load outputs:', e);
        setOutputItems([]);
      });
  }, [project]);

  const mentionCandidates = useMemo(() => {
    if (!mentionState) return [];
    const q = (mentionState.query || '').toLowerCase();

    const filterAndSlice = (items, labelKey, nameKey, sizeKey) => {
      const pool = items.map(item => ({
        label: String(item[labelKey] || ''),
        name: String(item[nameKey] || ''),
        ext: item.ext || (item.kind === 'xmind' ? '.md' : '.json'),
        size: item[sizeKey],
      }));
      if (!q) return pool.slice(0, 4);
      return pool.filter(r => r.label.toLowerCase().includes(q)).slice(0, 4);
    };

    // Legacy cases / xmind use file `name` (without extension) as @label.
    const stripExt = s => String(s || '').replace(/\.[^.]+$/, '');
    const lcPool = legacyCases.map(it => ({
      label: stripExt(it.name), name: it.name, ext: it.ext || '.xlsx',
      size: it.size, file_id: it.file_id,
    }));
    const xmPool = legacyXMind.map(it => ({
      label: stripExt(it.name), name: it.name, ext: it.ext || '.xmind',
      size: it.size, file_id: it.file_id,
    }));
    const lcFiltered = (q ? lcPool.filter(r => r.label.toLowerCase().includes(q)) : lcPool).slice(0, 4)
      .map(r => ({ ...r, category: 'legacy_case', catLabel: '历史用例' }));
    const xmFiltered = (q ? xmPool.filter(r => r.label.toLowerCase().includes(q)) : xmPool).slice(0, 4)
      .map(r => ({ ...r, category: 'legacy_xmind', catLabel: '历史 XMind' }));
    const reqDocs = filterAndSlice(docFiles, 'name', 'abs_path', 'size').map(r => ({ ...r, category: 'doc', catLabel: '需求文档' }));
    const tcOutputs = filterAndSlice(
      outputItems.filter(o => o.kind === 'testcase'), 'name', 'name', 'size'
    ).map(r => ({ ...r, category: 'out_tc', catLabel: '输出-测试用例' }));
    const xmOutputs = filterAndSlice(
      outputItems.filter(o => o.kind === 'xmind'), 'name', 'name', 'size'
    ).map(r => ({ ...r, category: 'out_xm', catLabel: '输出-XMind' }));

    return [...lcFiltered, ...xmFiltered, ...reqDocs, ...tcOutputs, ...xmOutputs];
  }, [legacyCases, legacyXMind, docFiles, outputItems, mentionState]);

  function handleInputChange(e) {
    const v = e.target.value;
    setInput(v);
    const cursor = e.target.selectionStart ?? v.length;
    // find last '@' before cursor (any position, not just after whitespace)
    let at = -1;
    for (let i = cursor - 1; i >= 0; i--) {
      const ch = v[i];
      if (ch === '@') {
        at = i;
        break;
      }
      // stop if we hit whitespace (the @ is part of a previous word)
      if (/\s/.test(ch)) break;
    }
    if (at >= 0) {
      const q = v.slice(at + 1, cursor);
      // only show suggestions if the text after @ doesn't contain spaces or another @
      if (/^[^\s@]*$/.test(q)) {
        setMentionState({ query: q, start: at });
        return;
      }
    }
    setMentionState(null);
  }

  function insertMention(label) {
    if (!mentionState || !textareaRef.current) return;
    const v = input;
    const end = (textareaRef.current.selectionStart ?? v.length);
    const before = v.slice(0, mentionState.start);
    const after = v.slice(end);
    const next = `${before}@${label} ${after}`;
    setInput(next);
    setMentionState(null);
    setTimeout(() => {
      if (textareaRef.current) {
        const pos = before.length + label.length + 2;
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(pos, pos);
      }
    }, 0);
  }

  function extractMentions(text) {
    if (!text) return [];
    const stripExt = s => String(s || '').replace(/\.[^.]+$/, '');
    const lcLabels = new Map(legacyCases.map(it => [
      stripExt(it.name).toLowerCase(),
      { type: 'legacy_case', file_id: it.file_id, name: it.name },
    ]));
    const xmLabels = new Map(legacyXMind.map(it => [
      stripExt(it.name).toLowerCase(),
      { type: 'legacy_xmind', file_id: it.file_id, name: it.name },
    ]));
    const docLabels = new Map(docFiles.map(f => {
      const base = f.name.replace(/\.[^.]+$/, '');
      return [base.toLowerCase(), { type: 'doc', path: f.abs_path, name: f.name }];
    }));
    const outputLabels = new Map(outputItems.map(o => {
      const base = o.name.replace(/\.[^.]+$/, '');
      return [base.toLowerCase(), { type: 'output', kind: o.kind, filename: o.name }];
    }));

    const allLabels = new Map([...lcLabels, ...xmLabels, ...docLabels, ...outputLabels]);
    const found = [];
    const seen = new Set();

    const re = /(?:^|\s)@([^\s@]+)/g;
    let m;
    while ((m = re.exec(text)) !== null) {
      const tok = m[1].toLowerCase();
      if (seen.has(tok)) continue;
      if (allLabels.has(tok)) {
        seen.add(tok);
        found.push(allLabels.get(tok));
        continue;
      }
      const cand = [...allLabels.keys()].filter(k => k.startsWith(tok));
      if (cand.length === 1) {
        seen.add(cand[0]);
        found.push(allLabels.get(cand[0]));
      }
    }
    return found;
  }

  const active = useMemo(
    () => {
      try {
        if (!activeId) return null;
        return chats.find(c => c.id === activeId) || null;
      } catch (e) {
        console.error('Error finding active chat:', e);
        setError('加载对话时出错：' + e.message);
        return null;
      }
    },
    [chats, activeId],
  );
  const mode = normalizeChatMode(active?.mode || selectedMode);

  useEffect(() => {
    if (project && chats.length === 0) {
      const c = newChat('qa');
      chatsApi.save([c]);
      chatsApi.setActive(c.id);
      setSelectedMode('qa');
    } else if (project && !active && chats.length > 0) {
      const existing = [...chats]
        .filter(c => normalizeChatMode(c.mode) === selectedMode)
        .sort((a, b) => ((b.updatedAt || b.createdAt || 0) - (a.updatedAt || a.createdAt || 0)));
      const next = existing[0] || [...chats].sort((a, b) => ((b.updatedAt || b.createdAt || 0) - (a.updatedAt || a.createdAt || 0)))[0];
      if (next) {
        setSelectedMode(normalizeChatMode(next.mode));
        chatsApi.setActive(next.id);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, chats.length, activeId]);

  // 同步已完成批次的最新状态
  const lastSyncedBatchRef = useRef({});  // { [batchId]: timestamp }
  async function syncCompletedBatches() {
    if (!project || !active) return;
    const msg = active.messages.find(m => m.batchManifest && !m._batchRunning);
    if (!msg?.batchManifest) return;
    
    const batchId = msg.batchManifest.batch_id;
    const now = Date.now();
    const lastSync = lastSyncedBatchRef.current[batchId] || 0;
    
    // 如果最近 5 秒内已经同步过，跳过以避免频繁请求
    if (now - lastSync < 5000) return;
    
    try {
      // 从后端重新获取最新的 manifest
      const latestManifest = await api.batchGet(project, batchId);
      // 更新本地状态
      mutateMsgByPredicate(active.id, m => m._batchKey === msg._batchKey, {
        batchManifest: latestManifest,
      });
      // 记录同步时间
      lastSyncedBatchRef.current[batchId] = now;
    } catch (e) {
      console.warn('Failed to sync batch manifest:', e);
    }
  }

  useEffect(() => {
    if (active) setSelectedMode(normalizeChatMode(active.mode));
  }, [active?.id, active?.mode]);

  // 当切换到有已完成批次的对话时，同步最新状态
  useEffect(() => {
    syncCompletedBatches();
  }, [active?.id, project]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [active?.messages?.length, busy]);

  // 流式模式下内容持续更新，需要更频繁的自动滚动
  useEffect(() => {
    if (!busy) return;
    const lastMsg = active?.messages?.[active.messages.length - 1];
    if (!lastMsg?._streaming) return;
    const timer = setInterval(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    }, 100);
    return () => clearInterval(timer);
  }, [busy, active?.messages]);

  function createNew() {
    const c = newChat(selectedMode);
    chatsApi.save([c, ...chats]);
    chatsApi.setActive(c.id);
  }

  // ---- batch flow message mutator + handlers --------------------------
  const batchStreamCtrlRef = useRef({});  // { [batchId]: controller }
  const [batchPreview, setBatchPreview] = useState(null);  // {name, content, kind}

  function mutateMsgByPredicate(chatId, predicate, patch) {
    const raw = localStorage.getItem(`casemind.chats.${project}`) || '[]';
    let arr;
    try { arr = JSON.parse(raw); } catch { return; }
    const next = arr.map(c => {
      if (c.id !== chatId) return c;
      const msgs = c.messages.map(m => predicate(m) ? { ...m, ...patch } : m);
      return { ...c, messages: msgs, updatedAt: Date.now() };
    });
    localStorage.setItem(`casemind.chats.${project}`, JSON.stringify(next));
    window.dispatchEvent(new Event('casemind:chats'));
  }

  function readMsg(chatId, predicate) {
    const arr = JSON.parse(localStorage.getItem(`casemind.chats.${project}`) || '[]');
    const chat = arr.find(c => c.id === chatId);
    return chat?.messages.find(predicate) || null;
  }

  function patchManifestUnit(chatId, draftMsgKey, unitId, patch, extra = {}) {
    const cur = readMsg(chatId, m => m._batchKey === draftMsgKey);
    if (!cur?.batchManifest) return;
    const mf = {
      ...cur.batchManifest,
      units: cur.batchManifest.units.map(u => u.unit_id === unitId ? { ...u, ...patch } : u),
    };
    mutateMsgByPredicate(chatId, m => m._batchKey === draftMsgKey, { batchManifest: mf, ...extra });
  }

  async function handleBatchConfirm(chatId, draftMsgKey, units, opts) {
    const msg = readMsg(chatId, m => m._batchKey === draftMsgKey);
    if (!msg?.batchDraft) return;
    const { question, kind, llmSnapshot, mentions, images } = msg.batchDraft;
    setBusy(true);
    try {
      const r = await api.batchStart(project, question, kind, units, llmSnapshot, {
        mentions: mentions || null,
        images: images || null,
        max_parallel: opts?.max_parallel || 1,
      });
      const manifest = r.manifest;
      mutateMsgByPredicate(chatId, m => m._batchKey === draftMsgKey, {
        batchDraft: null,
        batchManifest: manifest,
        _batchRunning: true,
      });

      const ctrl = api.batchRunStream(project, manifest.batch_id, llmSnapshot, {
        target_cases_per_unit: 50, only_pending: true,
      }, {
        async onEvent(evt) {
          if (evt.event === 'unit_started') {
            patchManifestUnit(chatId, draftMsgKey, evt.unit_id, { status: 'running' },
              { _currentUnitId: evt.unit_id });
          } else if (evt.event === 'unit_done' || evt.event === 'unit_failed') {
            patchManifestUnit(chatId, draftMsgKey, evt.unit_id, evt.unit || {});
          } else if (evt.event === 'batch_done') {
            // 从后端重新获取最新的 manifest 以确保状态一致
            try {
              const latestManifest = await api.batchGet(project, manifest.batch_id);
              mutateMsgByPredicate(chatId, m => m._batchKey === draftMsgKey, {
                _batchRunning: false,
                _currentUnitId: null,
                batchManifest: latestManifest,
              });
            } catch (e) {
              console.warn('Failed to fetch final manifest:', e);
              // 降级：使用事件中的 manifest
              mutateMsgByPredicate(chatId, m => m._batchKey === draftMsgKey, {
                _batchRunning: false,
                _currentUnitId: null,
              });
              if (evt.manifest) {
                mutateMsgByPredicate(chatId, m => m._batchKey === draftMsgKey, {
                  batchManifest: evt.manifest,
                });
              }
            }
            setBusy(false);
            delete batchStreamCtrlRef.current[manifest.batch_id];
            api.listOutputs(project).then(r => setOutputItems(r.outputs || [])).catch(() => {});
          }
        },
        onError(err) {
          mutateMsgByPredicate(chatId, m => m._batchKey === draftMsgKey, {
            _batchError: err.message || String(err), _batchRunning: false,
          });
          setBusy(false);
          delete batchStreamCtrlRef.current[manifest.batch_id];
        },
      });
      batchStreamCtrlRef.current[manifest.batch_id] = ctrl;
    } catch (e) {
      mutateMsgByPredicate(chatId, m => m._batchKey === draftMsgKey, {
        _batchError: e.message || String(e),
      });
      setBusy(false);
    }
  }

  function handleBatchCancel(chatId, draftMsgKey) {
    mutateMsgByPredicate(chatId, m => m._batchKey === draftMsgKey, {
      batchDraft: null,
      _batchCancelled: true,
    });
  }

  async function handleBatchDownload(manifest, fmt) {
    try {
      const fname = fmt === 'zip'
        ? `${manifest.batch_name}.zip`
        : (manifest.kind === 'testcase' ? `${manifest.batch_name}.xlsx` : `${manifest.batch_name}.md`);
      await api.batchDownload(project, manifest.batch_id, fmt, fname);
    } catch (e) {
      alert('下载失败：' + (e.message || e));
    }
  }

  async function handleBatchPreviewUnit(manifest, unit) {
    try {
      const r = await api.batchGetUnit(project, manifest.batch_id, unit.unit_id);
      if (r.missing) {
        alert('该模块文件尚未生成或已被删除。');
        return;
      }
      setBatchPreview({
        name: unit.output_file || `${unit.unit_id}.txt`,
        content: r.content || '',
        kind: manifest.kind,
      });
    } catch (e) {
      alert('查看失败：' + (e.message || e));
    }
  }

  function removeChat(id) {
    if (!confirm('删除此对话？')) return;
    const target = chats.find(c => c.id === id);
    const targetMode = normalizeChatMode(target?.mode || selectedMode);
    const next = chats.filter(c => c.id !== id);
    if (id === activeId) {
      const sameMode = [...next]
        .filter(c => normalizeChatMode(c.mode) === targetMode)
        .sort((a, b) => ((b.updatedAt || b.createdAt || 0) - (a.updatedAt || a.createdAt || 0)));
      if (sameMode.length > 0) {
        chatsApi.save(next);
        setSelectedMode(targetMode);
        chatsApi.setActive(sameMode[0].id);
      } else {
        const c = newChat(targetMode);
        chatsApi.save([c, ...next]);
        setSelectedMode(targetMode);
        chatsApi.setActive(c.id);
      }
    } else {
      chatsApi.save(next);
    }
  }

  function renameChat(id) {
    const target = chats.find(c => c.id === id);
    if (!target) return;
    const name = prompt('重命名对话', target.title || '新对话');
    if (name == null) return;
    chatsApi.save(chats.map(c => c.id === id ? { ...c, title: name.trim() || c.title } : c));
  }

  function selectMode(m) {
    const nextMode = normalizeChatMode(m);
    setSelectedMode(nextMode);
    if (active && active.messages.length === 0 && normalizeChatMode(active.mode) === nextMode) return;
    const existing = chats
      .filter(c => normalizeChatMode(c.mode) === nextMode)
      .sort((a, b) => ((b.updatedAt || b.createdAt || 0) - (a.updatedAt || a.createdAt || 0)));
    if (existing.length > 0) {
      chatsApi.setActive(existing[0].id);
    } else {
      const c = newChat(nextMode);
      chatsApi.save([c, ...chats]);
      chatsApi.setActive(c.id);
    }
  }

  // ---- image handlers ----
  function validateAndAddFiles(files) {
    const valid = [];
    for (const f of files) {
      const ext = '.' + (f.name || '').split('.').pop()?.toLowerCase();
      if (!ALLOWED_EXTENSIONS.has(ext)) {
        alert(`不支持的图片格式: ${ext}。允许: PNG, JPG, JPEG, GIF, WebP`);
        continue;
      }
      if (f.size > MAX_IMAGE_SIZE_MB * 1024 * 1024) {
        alert(`图片 ${f.name} 大小 ${(f.size / 1024 / 1024).toFixed(1)} MB 超过 ${MAX_IMAGE_SIZE_MB} MB 限制`);
        continue;
      }
      const previewUrl = URL.createObjectURL(f);
      valid.push({
        id: `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
        file: f,
        previewUrl,
      });
    }
    if (valid.length > 0) {
      setSelectedImages(prev => [...prev, ...valid]);
    }
  }

  function handleFileSelect(e) {
    const files = e.target.files;
    if (files && files.length > 0) {
      validateAndAddFiles(Array.from(files));
    }
    // reset input so same file can be re-selected
    if (fileInputRef.current) fileInputRef.current.value = '';
  }

  function removeImage(id) {
    setSelectedImages(prev => {
      const item = prev.find(p => p.id === id);
      if (item) URL.revokeObjectURL(item.previewUrl);
      return prev.filter(p => p.id !== id);
    });
  }

  function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(true);
  }

  function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    // Only set false if leaving the container itself (not a child)
    if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget)) {
      setIsDragOver(false);
    }
  }

  function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    setIsDragOver(false);
    const dt = e.dataTransfer;
    if (dt && dt.files && dt.files.length > 0) {
      validateAndAddFiles(Array.from(dt.files).filter(f => f.type.startsWith('image/')));
    }
  }

  function handlePaste(e) {
    const items = e.clipboardData?.items;
    if (!items || items.length === 0) return;
    const imageFiles = [];
    for (const item of items) {
      if (item.type && item.type.startsWith('image/')) {
        const blob = item.getAsFile();
        if (blob) {
          // 生成一个合理的文件名
          const ext = item.type.split('/')[1] || 'png';
          const renamed = new File([blob], `clipboard_${Date.now()}.${ext}`, { type: item.type });
          imageFiles.push(renamed);
        }
      }
    }
    if (imageFiles.length > 0) {
      e.preventDefault(); // 阻止默认粘贴行为（避免粘贴图片的 base64）
      validateAndAddFiles(imageFiles);
    }
  }

  function openViewer(urls, index) {
    setViewerImage({ urls, index });
  }

  function closeViewer() {
    setViewerImage(null);
  }

  function viewerPrev() {
    setViewerImage(prev => {
      if (!prev) return prev;
      return { ...prev, index: (prev.index - 1 + prev.urls.length) % prev.urls.length };
    });
  }

  function viewerNext() {
    setViewerImage(prev => {
      if (!prev) return prev;
      return { ...prev, index: (prev.index + 1) % prev.urls.length };
    });
  }

  // ---- keyboard handler for viewer ----
  useEffect(() => {
    if (!viewerImage) return;
    function onKey(e) {
      if (e.key === 'Escape') closeViewer();
      if (e.key === 'ArrowLeft') viewerPrev();
      if (e.key === 'ArrowRight') viewerNext();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [viewerImage]);

  async function send() {
    if (!project) { alert('请先选择项目'); return; }
    if (!active) { createNew(); return; }
    if (!input.trim() && selectedImages.length === 0) return;
    if (!llm.api_key) { alert('请先在「设置」填写 API Key'); return; }
    const q = input.trim();
    const imgs = [...selectedImages];
    setInput('');
    setSelectedImages([]);

    // 上传图片
    let imageUrls = [];
    if (imgs.length > 0) {
      try {
        const files = imgs.map(img => img.file);
        const uploadResult = await api.uploadImages(project, files);
        imageUrls = (uploadResult.images || []).map(r => r.url);
      } catch (e) {
        alert('图片上传失败：' + (e.message || e));
        // 恢复图片到预览列表
        setSelectedImages(imgs);
        return;
      }
      // 清理预览 URL
      imgs.forEach(img => URL.revokeObjectURL(img.previewUrl));
    }

    const content = q || (imageUrls.length > 0 ? '[图片]' : '');
    const history = buildChatHistory(active.messages);
    const msgUser = { role: 'user', content, images: imageUrls.length > 0 ? imageUrls : undefined };
    const isFirstMsg = active.messages.length === 0;

    // 1) persist user message immediately, then work off the snapshot
    //    (avoid reading stale `chats` via closure in the later updateActive call)
    const chatsAfterUser = chats.map(c => c.id === active.id ? ({
      ...c,
      messages: [...c.messages, msgUser],
      title: isFirstMsg ? smartTitle(q) : c.title,
      updatedAt: Date.now(),
    }) : c);
    chatsApi.save(chatsAfterUser);
    setBusy(true);
    const sendStart = performance.now();

    const mentions = extractMentions(q);
    const useStream = getStreamOutput();

    // 辅助函数：原地更新最后一条 AI 消息
    const updateLastMsg = (updater) => {
      const currentChats = JSON.parse(
        localStorage.getItem(`casemind.chats.${project}`) || '[]'
      );
      const updated = currentChats.map(c => {
        if (c.id !== active.id) return c;
        const msgs = [...c.messages];
        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], ...updater };
        return { ...c, messages: msgs, updatedAt: Date.now() };
      });
      localStorage.setItem(`casemind.chats.${project}`, JSON.stringify(updated));
      window.dispatchEvent(new Event('casemind:chats'));
    };

    // augment 模式不走流式
    if (mode === 'augment') {
      let msgAI;
      try {
        let displayText;
        if (imageUrls.length > 0) {
          displayText = '信息补充模式暂不支持图片分析，图片已保存但未用于记忆融合。';
        } else {
          const r = await api.augmentMemory(project, q, llm, '');
          displayText =
            `已将补充信息融合进系统记忆。\n` +
            `• 字符数：${r.info_chars}\n` +
            `• memory.md：${r.memory_md_path}\n\n` +
            `可在「记忆面板」查看合并后的索引。`;
        }
        msgAI = { role: 'assistant', content: displayText };
      } catch (e) {
        msgAI = { role: 'assistant', content: '错误：' + (e.message || e) };
      }
      const chatsAfterAI = chatsAfterUser.map(c => c.id === active.id ? ({
        ...c, messages: [...c.messages, msgAI], updatedAt: Date.now(),
      }) : c);
      chatsApi.save(chatsAfterAI);
      setBusy(false);
      return;
    }

    // 批量生成模式（testcase / xmind）— 先 AI 拆分 → 用户确认 → 串行/并发生成
    // 仅当用户勾选「AI 分模块」开关时启用；否则走下面的直生成（流式或非流式）
    if ((mode === 'testcase' || mode === 'xmind') && aiSplitEnabled) {
      const batchKey = `batch_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      const placeholderMsg = {
        role: 'assistant', content: '', _batchKey: batchKey, _batchSplitting: true,
      };
      let chatsWithPlaceholder = chatsAfterUser.map(c => c.id === active.id ? ({
        ...c, messages: [...c.messages, placeholderMsg], updatedAt: Date.now(),
      }) : c);
      chatsApi.save(chatsWithPlaceholder);

      try {
        const draft = await api.batchSplit(project, q, mode, llm, {
          mentions: mentions || null,
          images: imageUrls.length > 0 ? imageUrls : null,
          target_cases_per_unit: 50,
        });
        mutateMsgByPredicate(active.id, m => m._batchKey === batchKey, {
          _batchSplitting: false,
          batchDraft: {
            question: q,
            kind: mode,
            units: draft.units || [],
            rationale: draft.rationale || '',
            fallback: !!draft.fallback,
            llmSnapshot: llm,
            mentions: mentions || null,
            images: imageUrls.length > 0 ? imageUrls : null,
          },
        });
        // title fallback if first message
        if (isFirstMsg) {
          const arr = JSON.parse(localStorage.getItem(`casemind.chats.${project}`) || '[]');
          const updated = arr.map(c => c.id === active.id ? ({
            ...c, title: smartTitle(q),
          }) : c);
          localStorage.setItem(`casemind.chats.${project}`, JSON.stringify(updated));
          window.dispatchEvent(new Event('casemind:chats'));
        }
      } catch (e) {
        mutateMsgByPredicate(active.id, m => m._batchKey === batchKey, {
          _batchSplitting: false, _batchError: e.message || String(e),
        });
      }
      setBusy(false);
      return;
    }

    // 流式模式
    if (useStream) {
      // 插入占位 AI 消息
      const placeholderMsg = {
        role: 'assistant', content: '', thinking: '',
        sources: [], elapsedMs: 0, _streaming: true,
      };
      let chatsWithPlaceholder = chatsAfterUser.map(c => c.id === active.id ? ({
        ...c, messages: [...c.messages, placeholderMsg], updatedAt: Date.now(),
      }) : c);
      chatsApi.save(chatsWithPlaceholder);

      let streamThinking = '';
      let streamAnswer = '';

      const controller = api.queryStream(
        project, q, mode, llm, null, history, mentions,
        imageUrls.length > 0 ? imageUrls : null,
        {
          onThinking(text) {
            streamThinking += text;
            updateLastMsg({ content: streamAnswer, thinking: streamThinking, _streaming: true });
          },
          onAnswer(text) {
            streamAnswer += text;
            updateLastMsg({ content: streamAnswer, thinking: streamThinking, _streaming: true });
          },
          onDone(result) {
            const elapsedMs = Math.round(performance.now() - sendStart);
            const artifact = artifactFromResult(result);
            const summary = summaryFromResult(result);
            const isArtifactMode = mode === 'testcase' || mode === 'xmind';
            const finalContent = mode === 'req_analysis' && result?.data
              ? `__REQ_ANALYSIS__${JSON.stringify(result.data)}`
              : isArtifactMode
                ? ''
                : (streamAnswer || result?.answer || '');
            updateLastMsg({
              content: finalContent,
              thinking: streamThinking,
              sources: result?.sources || [],
              artifact,
              summary,
              elapsedMs,
              _streaming: false,
            });

            // 更新侧边栏最近结果
            if (mode === 'req_analysis' && result?.data) {
              setLast({ kind: 'req_analysis', payload: result, savedAt: Date.now() });
              setLastAnalysis(result.data);
            } else if (mode === 'testcase' && result?.data) {
              setLast({ kind: 'testcase', payload: result, savedAt: Date.now() });
            } else if (mode === 'xmind' && result?.output_file) {
              setLast({ kind: 'xmind', payload: result, savedAt: Date.now() });
            }

            setBusy(false);
            streamCtrlRef.current = null;
          },
          onError(err) {
            updateLastMsg({
              content: '错误：' + (err.message || String(err)),
              thinking: streamThinking, _streaming: false,
            });
            setBusy(false);
            streamCtrlRef.current = null;
          },
        }
      );
      streamCtrlRef.current = controller;
      return;
    }

    // 非流式模式
    let msgAI;
    try {
      let r, displayText = '', thinking = '', sources = [], artifact = null, summary = null;
      if (mode === 'req_analysis') {
        r = await api.query(project, q, mode, llm, null, history, mentions, imageUrls.length > 0 ? imageUrls : null);
        const analysisData = r.data || {};
        setLastAnalysis(analysisData);
        displayText = `__REQ_ANALYSIS__${JSON.stringify(analysisData)}`;
        artifact = artifactFromResult(r);
        summary = summaryFromResult(r);
        setLast({ kind: 'req_analysis', payload: r, savedAt: Date.now() });
      } else {
        r = await api.query(project, q, mode, llm, null, history, mentions, imageUrls.length > 0 ? imageUrls : null);
        sources = r.sources || [];
        artifact = artifactFromResult(r);
        summary = summaryFromResult(r);
        // 所有模式统一解析 thinking 标签
        const sp = splitThinking(r.answer || '');
        thinking = sp.thinking;
        const answerBody = sp.answer;

        if (r.mode === 'qa' || r.mode === 'chat') {
          displayText = answerBody;
        } else if (r.mode === 'testcase') {
          displayText = '';
          setLast({ kind: 'testcase', payload: r, savedAt: Date.now() });
        } else if (r.mode === 'xmind') {
          displayText = '';
          setLast({ kind: 'xmind', payload: r, savedAt: Date.now() });
        }
      }
      const elapsedMs = Math.round(performance.now() - sendStart);
      msgAI = { role: 'assistant', content: displayText, sources, thinking, artifact, summary, elapsedMs };
    } catch (e) {
      msgAI = { role: 'assistant', content: '错误：' + (e.message || e) };
    }

    // append AI message onto the *post-user* snapshot, not the stale closure
    const chatsAfterAI = chatsAfterUser.map(c => c.id === active.id ? ({
      ...c,
      messages: [...c.messages, msgAI],
      title: isFirstMsg && msgAI.role === 'assistant' && !msgAI.content.startsWith('错误：')
        ? smartTitle(q, msgAI.content) : c.title,
      updatedAt: Date.now(),
    }) : c);
    chatsApi.save(chatsAfterAI);
    setBusy(false);
  }

  async function handleDownloadPDF(artifact = null, analysisData = null) {
    if (artifact?.pdfFilename || (artifact?.kind === 'req_analysis' && artifact?.filename)) {
      await api.downloadOutput(project, 'req_analysis', artifact.pdfFilename || artifact.filename);
      return;
    }
    const data = analysisData || lastAnalysis;
    if (!data || !project) {
      alert('暂无分析数据');
      return;
    }
    const result = await api.generateReqAnalysisReport(project, data);
    if (result.pdf_base64) {
      // 将 base64 转为 Blob 并触发下载
      const byteChars = atob(result.pdf_base64);
      const byteNums = new Array(byteChars.length);
      for (let i = 0; i < byteChars.length; i++) {
        byteNums[i] = byteChars.charCodeAt(i);
      }
      const byteArr = new Uint8Array(byteNums);
      const blob = new Blob([byteArr], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = result.filename || `需求分析报告_${project}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  }

  const chatGroups = groupChatsByMode(chats);
  const selectedGroup = chatGroups.find(g => g.key === selectedMode) || chatGroups[0];
  const modeIcons = {
    qa: 'help',
    chat: 'chat',
    testcase: 'fact_check',
    xmind: 'account_tree',
    req_analysis: 'assignment',
    augment: 'add_notes',
  };

  const renderChatItem = (c) => (
    <div
      key={c.id}
      className={`chat-item ${c.id === activeId ? 'active' : ''}`}
      onClick={() => {
        setSelectedMode(normalizeChatMode(c.mode));
        chatsApi.setActive(c.id);
      }}
    >
      <div className="chat-item-title">{c.title || '新对话'}</div>
      <div className="chat-item-meta">
        {modeLabel(c.mode)}
        <span className="muted"> · {c.messages.length} 条</span>
      </div>
      <div className="chat-item-actions">
        <button className="icon-btn" onClick={(e) => { e.stopPropagation(); renameChat(c.id); }} title="重命名">
          <span className="mi" style={{ fontSize: 14 }}>edit</span>
        </button>
        <button className="icon-btn" onClick={(e) => { e.stopPropagation(); removeChat(c.id); }} title="删除">
          <span className="mi" style={{ fontSize: 14 }}>close</span>
        </button>
      </div>
    </div>
  );
  return (
    <div className="chat-layout">
      {error && (
        <div className="card" style={{ borderColor: '#cf6679', background: 'rgba(207,102,121,0.1)', marginBottom: 16 }}>
          <p style={{ color: '#cf6679', margin: 0 }}>
            <span className="mi" style={{ verticalAlign: -2, marginRight: 6 }}>error</span>
            {error}
          </p>
          <button className="ghost" onClick={() => setError(null)} style={{ marginTop: 8 }}>关闭</button>
        </div>
      )}
      <aside className="chat-list">
        <div className="chat-mode-rail">
          {chatGroups.map(g => (
            <button
              key={g.key}
              className={`chat-mode-item ${selectedMode === g.key ? 'active' : ''}`}
              onClick={() => selectMode(g.key)}
              title={g.label}
            >
              <span className="mi">{modeIcons[g.key]}</span>
              <span className="chat-mode-label">{g.label}</span>
              <span className="chat-mode-count">{g.items.length}</span>
            </button>
          ))}
        </div>
        <div className="chat-session-pane">
          <div className="chat-list-title">
            <span>{selectedGroup?.label || '问答'}</span>
            <button className="icon-btn" onClick={createNew} title="新对话">
              <span className="mi">edit_square</span>
            </button>
          </div>
          {selectedGroup?.items.length === 0 ? (
            <div className="chat-empty-state">
              <span className="mi">forum</span>
              <p>暂无会话</p>
              <button className="ghost" onClick={createNew}>新建对话</button>
            </div>
          ) : (
            selectedGroup.items.map(renderChatItem)
          )}
        </div>
      </aside>

      <div>
        <div className="page-head" style={{ marginBottom: 16 }}>
          <div>
            <div className="page-title" style={{ fontSize: 24 }}>
              AI 对话
              <span className="badge-pro" style={{ marginLeft: 8 }}>{project || '未选择项目'}</span>
            </div>
            <div className="page-sub">自动附带当前项目记忆 + 向量检索 + 本会话历史。</div>
          </div>
        </div>

        <div
          ref={scrollRef}
          className="card"
          style={{
            display: 'flex', flexDirection: 'column', gap: 16,
            maxHeight: 'calc(100vh - 340px)', overflow: 'auto',
            padding: 24,
          }}
        >
          {(!active || active.messages.length === 0) && (
            <p className="muted" style={{ textAlign: 'center', padding: '40px 0' }}>
              输入你的问题，例如：&quot;登录模块有哪些测试用例？&quot;
            </p>
          )}
          {active?.messages.map((m, i) => {
            const isReqAnalysis = typeof m.content === 'string' && m.content.startsWith('__REQ_ANALYSIS__');
            let analysisData = null;
            let displayContent = m.content;
            if (isReqAnalysis) {
              try {
                analysisData = JSON.parse(m.content.slice('__REQ_ANALYSIS__'.length));
                displayContent = '';
              } catch {}
            }
            const hasImages = m.images && m.images.length > 0;
            return (
            <div key={i} className={`bubble ${m.role === 'assistant' ? 'ai' : 'user'}`}>
              {m.role === 'assistant' && <ThinkingBlock text={m.thinking} elapsedMs={m.elapsedMs} streaming={m._streaming} />}
              {/* 用户消息中的图片 */}
              {hasImages && (
                <div className="message-images">
                  {m.images.map((url, idx) => (
                    <div
                      key={idx}
                      className="message-image-card"
                      onClick={() => openViewer(m.images, idx)}
                      title="点击查看大图"
                    >
                      <img src={url} alt={`图片 ${idx + 1}`} loading="lazy" />
                    </div>
                  ))}
                </div>
              )}
              {isReqAnalysis && analysisData ? (
                <ReqAnalysisCard data={analysisData} onDownloadPDF={() => handleDownloadPDF(m.artifact, analysisData)} />
              ) : m._batchSplitting ? (
                <div className="row" style={{ gap: 8, alignItems: 'center' }}>
                  <span className="mi" style={{ color: '#cfbcff', animation: 'pulse 1.4s infinite' }}>auto_awesome</span>
                  <span className="muted">AI 正在拆分模块…</span>
                </div>
              ) : m._batchError && !m.batchDraft && !m.batchManifest ? (
                <div className="err">批量生成失败：{m._batchError}</div>
              ) : m.batchDraft ? (
                <UnitDraftCard
                  draft={m.batchDraft}
                  disabled={busy}
                  onConfirm={(units, opts) => handleBatchConfirm(active.id, m._batchKey, units, opts)}
                  onCancel={() => handleBatchCancel(active.id, m._batchKey)}
                />
              ) : m.batchManifest && m._batchRunning ? (
                <BatchProgressCard
                  batchName={m.batchManifest.batch_name}
                  kind={m.batchManifest.kind}
                  units={m.batchManifest.units}
                  currentUnitId={m._currentUnitId}
                  batchStatus="running"
                />
              ) : m.batchManifest ? (
                <BatchResultCard
                  manifest={m.batchManifest}
                  onDownload={(fmt) => handleBatchDownload(m.batchManifest, fmt)}
                  onPreviewUnit={(u) => handleBatchPreviewUnit(m.batchManifest, u)}
                />
              ) : m.summary && (m.summary.kind === 'testcase' || m.summary.kind === 'xmind') ? (
                <ArtifactSummaryCard summary={m.summary} />
              ) : (
                <div>{displayContent}</div>
              )}
              {!isReqAnalysis && !m.batchDraft && !m.batchManifest && <ArtifactActions project={project} artifact={m.artifact} />}
              {m.role === 'assistant' && <CitationBlock sources={m.sources} />}
            </div>
            );
          })}
          {busy && (() => {
            const last = active?.messages?.[active.messages.length - 1];
            if (last?._streaming) return false;
            if (last?._batchSplitting || last?._batchRunning || last?.batchDraft || last?.batchManifest) return false;
            return true;
          })() && (
            <div className="bubble ai" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span className="mi" style={{ color: '#cfbcff', animation: 'pulse 1.4s infinite' }}>auto_awesome</span>
              <span className="muted">{mode === 'req_analysis' ? '正在分析需求文档…' : mode === 'chat' ? '正在生成回答…' : '正在检索并生成回答…'}</span>
            </div>
          )}
        </div>

        <div
          className={`card image-upload-area ${isDragOver ? 'drag-over' : ''}`}
          style={{ marginTop: 16, position: 'relative' }}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          {/* 隐藏的文件选择 input */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".png,.jpg,.jpeg,.gif,.webp"
            multiple
            style={{ display: 'none' }}
            onChange={handleFileSelect}
          />
          {/* 图片预览列表 */}
          {selectedImages.length > 0 && (
            <div className="image-preview-list">
              {selectedImages.map((img) => (
                <div key={img.id} className="image-preview-item">
                  <img src={img.previewUrl} alt={img.file.name} />
                  <button
                    className="remove-btn"
                    onClick={() => removeImage(img.id)}
                    title="移除此图片"
                  >
                    <span className="mi" style={{ fontSize: 14 }}>close</span>
                  </button>
                </div>
              ))}
            </div>
          )}
          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInputChange}
            onSelect={handleInputChange}
            onPaste={handlePaste}
            placeholder={
              mode === 'augment'
                ? '粘贴你希望补充进项目记忆的内容（新需求说明、业务规则、字段定义、术语澄清、决策记录…），Enter 发送。系统会把它融入 memory.md 索引。'
                : mode === 'req_analysis'
                ? '粘贴或输入需求文档内容（PRD、需求规格说明等），AI 将自动分析其中的矛盾、遗漏、逻辑漏洞和风险。也可使用 @ 引用已上传的需求文档。'
                : mode === 'chat'
                ? '随便聊点什么，Enter 发送，Shift+Enter 换行。此模式不检索项目文档。'
                : '描述你需要生成的内容，Enter 发送，Shift+Enter 换行。输入 @ 可引用文件。'
            }
            onKeyDown={e => {
              if (mentionState && mentionCandidates.length > 0) {
                if (e.key === 'Escape') { setMentionState(null); e.preventDefault(); return; }
                if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && !e.isComposing)) {
                  e.preventDefault();
                  insertMention(mentionCandidates[0].label);
                  return;
                }
              }
              if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
                e.preventDefault();
                send();
              }
            }}
          />
          {mentionState && mentionCandidates.length > 0 && (
            <div style={{
              position: 'absolute', left: 20, bottom: 'calc(100% - 8px)',
              background: 'rgba(29,27,32,0.95)',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(207,188,255,0.3)',
              borderRadius: 12,
              padding: 6,
              minWidth: 300,
              maxHeight: 360,
              overflow: 'auto',
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
              zIndex: 20,
            }}>
              <div className="muted mono" style={{ padding: '4px 10px', fontSize: 10, letterSpacing: '0.14em', textTransform: 'uppercase' }}>
                引用文件 · 按 Tab/Enter 选中
              </div>
              {(() => {
                const categories = ['历史用例', '历史 XMind', '需求文档', '输出-测试用例', '输出-XMind'];
                let globalIdx = 0;
                return categories.map(cat => {
                  const items = mentionCandidates.filter(mc => mc.catLabel === cat);
                  if (items.length === 0) return null;
                  return (
                    <div key={cat}>
                      <div className="muted" style={{ padding: '6px 10px 2px', fontSize: 10, letterSpacing: '0.1em' }}>
                        {cat}
                      </div>
                      {items.map(c => {
                        const idx = globalIdx++;
                        const icon = c.category === 'legacy_case' ? 'table_chart'
                          : c.category === 'legacy_xmind' ? 'account_tree'
                          : c.category === 'doc' ? 'description'
                          : c.category === 'out_tc' ? 'fact_check' : 'account_tree';
                        const iconColor = c.category === 'legacy_case' ? '#7fd9a8'
                          : c.category === 'legacy_xmind' ? '#e7c365'
                          : c.category === 'doc' ? '#85c1e9'
                          : c.category === 'out_tc' ? '#cfbcff' : '#e7c365';
                        return (
                          <div
                            key={`${c.category}:${c.name}`}
                            onClick={() => insertMention(c.label)}
                            style={{
                              padding: '8px 10px', borderRadius: 8, cursor: 'pointer',
                              background: idx === 0 ? 'rgba(103,80,164,0.25)' : 'transparent',
                              display: 'flex', alignItems: 'center', gap: 8,
                            }}
                            onMouseEnter={e => e.currentTarget.style.background = 'rgba(103,80,164,0.25)'}
                            onMouseLeave={e => e.currentTarget.style.background = idx === 0 ? 'rgba(103,80,164,0.25)' : 'transparent'}
                          >
                            <span className="mi" style={{ fontSize: 16, color: iconColor }}>{icon}</span>
                            <span style={{ fontSize: 13, color: '#e6e0e9' }}>@{c.label}</span>
                            <span className="mono muted" style={{ fontSize: 11, marginLeft: 'auto' }}>{c.ext}</span>
                          </div>
                        );
                      })}
                    </div>
                  );
                });
              })()}
            </div>
          )}
          <div className="row" style={{ marginTop: 10, justifyContent: 'space-between' }}>
            <span className="muted">
              <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>model_training</span>
              {llm.model || '未配置模型'}
            </span>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <AiModelSelect
                value={selectedModel}
                onChange={setSelectedModel}
                defaultModel={defaultModel}
                disabled={busy}
                title="选择本次对话模型"
              />
              {(mode === 'testcase' || mode === 'xmind') && (
                <label
                  title="开启后：AI 先把需求拆成多个模块，确认后逐模块生成（适合大需求）；关闭：直接一次性生成（速度快、适合冒烟）"
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6,
                    padding: '4px 10px', borderRadius: 8, fontSize: 12,
                    border: '1px solid #2d2b33',
                    background: aiSplitEnabled ? 'rgba(207,188,255,0.14)' : 'transparent',
                    color: aiSplitEnabled ? '#cfbcff' : '#b5afbd',
                    cursor: busy ? 'not-allowed' : 'pointer',
                    opacity: busy ? 0.6 : 1,
                    userSelect: 'none',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={aiSplitEnabled}
                    disabled={busy}
                    onChange={e => setAiSplitEnabled(e.target.checked)}
                    style={{ accentColor: '#cfbcff', margin: 0 }}
                  />
                  <span className="mi" style={{ fontSize: 14 }}>auto_awesome</span>
                  AI 分模块
                </label>
              )}
              <button
                className="upload-icon-btn"
                onClick={() => fileInputRef.current?.click()}
                title="上传图片 (支持拖拽和 Ctrl+V 粘贴)"
                disabled={busy}
              >
                <span className="mi" style={{ fontSize: 20 }}>image</span>
              </button>
              {busy ? (
                <button
                  className="primary"
                  onClick={() => {
                    streamCtrlRef.current?.abort();
                    streamCtrlRef.current = null;
                    // 清除占位消息的 _streaming 状态
                    const currentChats = JSON.parse(
                      localStorage.getItem(`casemind.chats.${project}`) || '[]'
                    );
                    const updated = currentChats.map(c => {
                      if (c.id !== active.id) return c;
                      const msgs = [...c.messages];
                      if (msgs.length > 0 && msgs[msgs.length - 1]._streaming) {
                        msgs[msgs.length - 1] = { ...msgs[msgs.length - 1], _streaming: false };
                      }
                      return { ...c, messages: msgs, updatedAt: Date.now() };
                    });
                    localStorage.setItem(`casemind.chats.${project}`, JSON.stringify(updated));
                    window.dispatchEvent(new Event('casemind:chats'));
                    setBusy(false);
                  }}
                  style={{ background: 'linear-gradient(135deg, #ffb4ab, #cf6679)' }}
                >
                  <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>stop</span>
                  停止
                </button>
              ) : (
                <button className="primary" onClick={send}>
                  <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>send</span>
                  发送
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
      {/* 图片查看器 */}
      {viewerImage && (
        <div className="image-viewer-overlay" onClick={closeViewer}>
          <button className="image-viewer-close" onClick={closeViewer} title="关闭 (Esc)">
            <span className="mi">close</span>
          </button>
          {viewerImage.urls.length > 1 && (
            <>
              <button
                className="image-viewer-nav prev"
                onClick={(e) => { e.stopPropagation(); viewerPrev(); }}
                title="上一张 (←)"
              >
                <span className="mi">chevron_left</span>
              </button>
              <button
                className="image-viewer-nav next"
                onClick={(e) => { e.stopPropagation(); viewerNext(); }}
                title="下一张 (→)"
              >
                <span className="mi">chevron_right</span>
              </button>
            </>
          )}
          <img
            src={viewerImage.urls[viewerImage.index]}
            alt={`图片 ${viewerImage.index + 1}`}
            onClick={(e) => e.stopPropagation()}
          />
          {viewerImage.urls.length > 1 && (
            <div className="image-viewer-counter">
              {viewerImage.index + 1} / {viewerImage.urls.length}
            </div>
          )}
        </div>
      )}
      {/* 批次单元预览 modal —— 与 AI 用例库 / 单次生成一致的格式 */}
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
            className="image-viewer-overlay"
            onClick={() => setBatchPreview(null)}
            style={{ background: 'rgba(8,6,12,0.85)' }}
          >
            <div
              className="card"
              onClick={(e) => e.stopPropagation()}
              style={{
                padding: 16, maxWidth: '92vw', maxHeight: '88vh',
                width: 1100, display: 'flex', flexDirection: 'column', gap: 10,
              }}
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
                <button className="ghost" onClick={() => setBatchPreview(null)} style={{ padding: '2px 8px' }}>
                  <span className="mi" style={{ fontSize: 16, verticalAlign: -3 }}>close</span>
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
              <div className="row" style={{ justifyContent: 'flex-end', gap: 6 }}>
                <button
                  className="ghost"
                  onClick={() => {
                    navigator.clipboard?.writeText(batchPreview.content).then(
                      () => alert('已复制原始内容到剪贴板'),
                      () => alert('复制失败'),
                    );
                  }}
                  style={{ padding: '4px 12px', fontSize: 12 }}
                >
                  <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>content_copy</span>
                  复制原始内容
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

