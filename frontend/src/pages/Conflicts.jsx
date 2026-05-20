import React, { useEffect, useState } from 'react';
import { api } from '../api.js';
import { useLLM, useProject } from '../store.js';

const TYPE_LABEL = {
  numeric: '数值',
  enum: '枚举',
  rule: '规则',
  flow: '流程',
  acceptance: '验收',
  other: '其他',
};

const RESOLUTION_LABEL = {
  unresolved: '未处置',
  accept_first: '以首条为准',
  accept_second: '以第二条为准',
  manual: '手工合并',
  false_positive: '误报',
};

const SEV_COLOR = { high: '#ffb4ab', medium: '#e7c365', low: '#7fd9a8' };

function fmtTime(iso) {
  if (!iso) return '';
  return iso.replace('T', ' ').replace(/\..*/, '').replace('Z', '');
}

export default function Conflicts() {
  const [project] = useProject();
  const [llm] = useLLM();
  const [list, setList] = useState([]);
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState('all'); // all | unresolved | resolved

  async function refresh() {
    setErr('');
    if (!project) return;
    try {
      const r = await api.cfList(project);
      setList(r.conflicts || []);
    } catch (e) { setErr(String(e.message || e)); }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [project]);

  async function runDetect() {
    if (!project) { setErr('请先选择项目'); return; }
    if (!llm.api_key) { setErr('请先在「设置」填写 API Key'); return; }
    setBusy(true); setErr(''); setMsg('');
    try {
      const r = await api.cfDetect(project, llm);
      setMsg(
        `检测完成：扫描 KP ${r.stats.eligible_kps} · 候选 ${r.stats.candidate_pairs} · ` +
        `LLM 判 ${r.stats.judged_pairs} · 新增 ${r.stats.new_conflicts}`
      );
      await refresh();
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  }

  async function resolve(c, resolution) {
    let note = '';
    if (resolution === 'manual' || resolution === 'false_positive') {
      note = window.prompt(`备注（${RESOLUTION_LABEL[resolution]}）：`, '') || '';
    }
    setBusy(true); setErr('');
    try {
      await api.cfResolve(project, c.conflict_id, resolution, note);
      await refresh();
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  }

  async function del(c) {
    if (!window.confirm(`删除冲突 ${c.conflict_id}？`)) return;
    setBusy(true); setErr('');
    try {
      await api.cfDelete(project, c.conflict_id);
      await refresh();
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  }

  async function clearAll() {
    if (!window.confirm(`清空项目「${project}」全部冲突记录？`)) return;
    setBusy(true); setErr('');
    try {
      await api.cfClear(project);
      await refresh();
      setMsg('已清空');
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  }

  const filtered = list.filter(c => {
    if (filter === 'unresolved') return c.resolution === 'unresolved';
    if (filter === 'resolved') return c.resolution !== 'unresolved';
    return true;
  });

  const counts = {
    total: list.length,
    unresolved: list.filter(c => c.resolution === 'unresolved').length,
    resolved: list.length - list.filter(c => c.resolution === 'unresolved').length,
  };

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="page-title">需求冲突检测</div>
          <div className="page-sub">
            扫描项目全部 KnowledgePoint，按模块分桶后用向量相似度+LLM 裁判识别跨文档冲突。
            结果落盘，可标注处置，不会重复检测同一对。
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="primary" disabled={busy || !project} onClick={runDetect}>
            <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>search</span>
            运行检测
          </button>
          <button className="ghost" disabled={busy || list.length === 0} onClick={clearAll}>
            <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>delete_sweep</span>
            清空
          </button>
        </div>
      </div>

      {err && <div className="err" style={{ marginBottom: 10 }}>{err}</div>}
      {msg && <div className="ok"  style={{ marginBottom: 10 }}>{msg}</div>}
      {!project && <div className="muted">请先在「项目管理」选择一个项目。</div>}

      {project && (
        <>
          <div style={{ display: 'flex', gap: 12, marginBottom: 12, alignItems: 'center' }}>
            <div className="muted" style={{ fontSize: 12 }}>
              共 <b style={{ color: '#e6e0e9' }}>{counts.total}</b> 条 ·
              未处置 <b style={{ color: '#ffb4ab' }}>{counts.unresolved}</b> ·
              已处置 <b style={{ color: '#7fd9a8' }}>{counts.resolved}</b>
            </div>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
              {[['all', '全部'], ['unresolved', '未处置'], ['resolved', '已处置']].map(([k, label]) => (
                <button
                  key={k}
                  onClick={() => setFilter(k)}
                  className={filter === k ? 'active' : 'ghost'}
                  style={{ padding: '4px 12px', fontSize: 12 }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {filtered.length === 0 && (
            <div className="card" style={{ margin: 0 }}>
              <div className="muted">暂无符合条件的冲突。</div>
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {filtered.map(c => (
              <div key={c.conflict_id} className="card" style={{ margin: 0 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span className="mono" style={{ fontSize: 11, color: '#948e9c' }}>{c.conflict_id}</span>
                  <span className="tag info" style={{ fontSize: 10 }}>{TYPE_LABEL[c.type] || c.type}</span>
                  <span className="tag" style={{ fontSize: 10, color: SEV_COLOR[c.severity] }}>
                    {c.severity}
                  </span>
                  {c.module && <span className="tag" style={{ fontSize: 10 }}>{c.module}</span>}
                  <span className="tag" style={{
                    fontSize: 10,
                    background: c.resolution === 'unresolved'
                      ? 'rgba(255,180,171,0.18)'
                      : 'rgba(127,217,168,0.18)',
                  }}>
                    {RESOLUTION_LABEL[c.resolution] || c.resolution}
                  </span>
                  <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
                    {fmtTime(c.detected_at)}
                  </span>
                </div>

                <div style={{ marginTop: 8, fontSize: 14, fontWeight: 500 }}>{c.description}</div>
                {c.evidence && (
                  <div className="muted" style={{ marginTop: 4, fontSize: 12, fontStyle: 'italic' }}>
                    证据：{c.evidence}
                  </div>
                )}

                <div style={{ marginTop: 10, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  {(c.kp_ids || []).map((kpid, i) => (
                    <div key={kpid} style={{
                      padding: '8px 10px', borderRadius: 6,
                      border: '1px solid #2b292f', background: '#1a191d',
                    }}>
                      <div className="mono" style={{ fontSize: 11, color: '#948e9c' }}>{kpid}</div>
                      <div style={{ marginTop: 4, fontSize: 13, lineHeight: 1.5 }}>
                        {c.kp_contents?.[i] || '—'}
                      </div>
                    </div>
                  ))}
                </div>

                {c.resolution_note && (
                  <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                    备注：{c.resolution_note}
                  </div>
                )}

                <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <button className="ghost" disabled={busy}
                          onClick={() => resolve(c, 'accept_first')}>
                    <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>check</span>
                    以首条为准
                  </button>
                  <button className="ghost" disabled={busy}
                          onClick={() => resolve(c, 'accept_second')}>
                    <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>check</span>
                    以第二条为准
                  </button>
                  <button className="ghost" disabled={busy}
                          onClick={() => resolve(c, 'manual')}>
                    <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>edit_note</span>
                    手工合并
                  </button>
                  <button className="ghost" disabled={busy}
                          onClick={() => resolve(c, 'false_positive')}>
                    <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>flag</span>
                    误报
                  </button>
                  {c.resolution !== 'unresolved' && (
                    <button className="ghost" disabled={busy}
                            onClick={() => resolve(c, 'unresolved')}>
                      <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>restart_alt</span>
                      重置
                    </button>
                  )}
                  <button className="ghost" disabled={busy}
                          onClick={() => del(c)}
                          style={{ marginLeft: 'auto', color: '#ffb4ab' }}>
                    <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>delete</span>
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
