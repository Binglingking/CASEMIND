import React, { useEffect, useState } from 'react';
import { api } from '../api.js';
import { useProject } from '../store.js';
import AiModelSelect, { useScopedLLM } from '../components/AiModelSelect.jsx';

const STEP_LABELS = {
  1: 'Step1 · Slicer（需求切片）',
  2: 'Step2 · Generator（并行生成）',
  3: 'Step3 · Merger（归并/跨切片）',
  4: 'Step4 · Validator（引用校验）',
};

function StatusTag({ status }) {
  const map = {
    pending:              { cls: 'tag',      txt: '待跑' },
    running:              { cls: 'tag warn', txt: '运行中' },
    done:                 { cls: 'tag ok',   txt: '完成' },
    failed:               { cls: 'tag err',  txt: '失败' },
    user_edited_pending:  { cls: 'tag info', txt: '已编辑/待重跑' },
  };
  const s = map[status] || { cls: 'tag', txt: status };
  return <span className={s.cls} style={{ fontSize: 11 }}>{s.txt}</span>;
}

function fmtTime(iso) {
  if (!iso) return '';
  return iso.replace('T', ' ').replace(/\..*/, '').replace('Z', '');
}

export default function CaseGen() {
  const [project] = useProject();
  const [llm, selectedModel, setSelectedModel, defaultModel] = useScopedLLM('case-gen');
  const [list, setList] = useState([]);
  const [selected, setSelected] = useState(null);   // {state, step_outputs}
  const [pid, setPid] = useState('');
  const [question, setQuestion] = useState('');
  const [err, setErr] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);
  const [coverage, setCoverage] = useState(null);
  const [covBusy, setCovBusy] = useState(false);
  const [fbEnabled, setFbEnabled] = useState(false);
  const [fbByCase, setFbByCase] = useState({});  // case_id -> latest feedback (kind, feedback_id)

  async function refreshList() {
    setErr('');
    if (!project) return;
    try {
      const r = await api.cgList(project);
      setList(r.pipelines || []);
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function loadPipeline(thePid) {
    setErr('');
    if (!project || !thePid) return;
    try {
      const r = await api.cgGet(project, thePid);
      setSelected(r);
      setPid(thePid);
      // 附带尝试加载已缓存覆盖率
      try {
        const cov = await api.covGet(project, thePid);
        setCoverage(cov);
      } catch { setCoverage(null); }
    } catch (e) { setErr(String(e.message || e)); }
  }

  useEffect(() => {
    refreshList();
    setSelected(null); setPid(''); setCoverage(null);
    setFbByCase({});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project]);

  // 订阅 feature flag：enable_feedback_loop 决定是否显示反馈按钮
  async function reloadFlag() {
    try {
      const f = await api.getFeatures();
      setFbEnabled(!!f?.enable_feedback_loop);
    } catch { setFbEnabled(false); }
  }
  useEffect(() => {
    reloadFlag();
    const h = () => reloadFlag();
    window.addEventListener('casemind:features', h);
    return () => window.removeEventListener('casemind:features', h);
  }, []);

  // 项目/开关变更时拉一次当前项目下的反馈，建立 case_id → 最新反馈 map
  async function refreshFeedbackIndex() {
    if (!project || !fbEnabled) { setFbByCase({}); return; }
    try {
      const r = await api.fbList(project);
      const map = {};
      for (const fb of r.feedback || []) {
        const prev = map[fb.target_id];
        if (!prev || fb.created_at > prev.created_at) {
          map[fb.target_id] = fb;
        }
      }
      setFbByCase(map);
    } catch { /* 静默；按钮仍可用 */ }
  }
  useEffect(() => { refreshFeedbackIndex(); /* eslint-disable-next-line */ },
            [project, fbEnabled, pid]);

  async function startNew() {
    if (!project) { setErr('请先选择项目'); return; }
    if (!llm.api_key) { setErr('请先在「设置」填写 API Key'); return; }
    if (!question.trim()) { setErr('请输入流水线问题/需求描述'); return; }
    setBusy(true); setErr(''); setMsg('');
    try {
      const st = await api.cgStart(project, question.trim(), llm);
      setQuestion('');
      setMsg(`已创建流水线 ${st.pipeline_id}`);
      await refreshList();
      await loadPipeline(st.pipeline_id);
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  }

  async function runStep(n) {
    if (!pid) return;
    if (!llm.api_key) { setErr('请先在「设置」填写 API Key'); return; }
    setBusy(true); setErr(''); setMsg('');
    try {
      await api.cgRunStep(project, pid, n, llm);
      setMsg(`Step${n} 已完成`);
      await loadPipeline(pid);
      await refreshList();
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  }

  async function rollback(n) {
    if (!pid) return;
    if (!window.confirm(`回滚到 Step${n}？Step${n} 及之后产物将被清空。`)) return;
    setBusy(true); setErr(''); setMsg('');
    try {
      await api.cgRollback(project, pid, n);
      setMsg(`已回滚至 Step${n}`);
      await loadPipeline(pid);
    } catch (e) { setErr(String(e.message || e)); }
    setBusy(false);
  }

  async function computeCoverage() {
    if (!pid) return;
    setCovBusy(true); setErr(''); setMsg('');
    try {
      const r = await api.covCompute(project, pid, { sim_threshold: 0.75, enable_semantic: true });
      setCoverage(r);
      setMsg('覆盖率已计算');
    } catch (e) { setErr(String(e.message || e)); }
    setCovBusy(false);
  }

  const state = selected?.state;
  const outputs = selected?.step_outputs || {};
  // step4 走 valid_cases；step3 走 merged_cases；step2 走 by_fp 聚合
  const cases = (() => {
    if (outputs['4']?.valid_cases) return outputs['4'].valid_cases;
    if (outputs['3']?.merged_cases) return outputs['3'].merged_cases;
    const byFp = outputs['2']?.by_fp;
    if (byFp) {
      const out = [];
      for (const block of Object.values(byFp)) {
        for (const c of (block?.cases || [])) out.push(c);
      }
      return out;
    }
    return null;
  })();

  // fp_id → module（来自 step1 产物）
  const fpModuleMap = {};
  for (const fp of outputs['1']?.feature_points || []) {
    fpModuleMap[fp.fp_id] = fp.module;
  }

  async function sendFeedback(c, kind) {
    if (!project || !c?.case_id) return;
    let note = '';
    if (kind === 'down') {
      note = window.prompt('（可选）说下不满意的原因：', '') || '';
    }
    try {
      const mod = fpModuleMap[c.feature_point] || '';
      await api.fbSubmit(project, {
        target_id: c.case_id,
        kind,
        target_type: 'case',
        pipeline_id: pid || null,
        module: mod || null,
        note,
        snapshot: c,
      });
      await refreshFeedbackIndex();
      setMsg(`已记录反馈：${c.case_id} · ${kind}`);
    } catch (e) { setErr(String(e.message || e)); }
  }

  async function withdrawFeedback(c) {
    const fb = fbByCase[c.case_id];
    if (!fb) return;
    try {
      await api.fbDelete(project, fb.feedback_id);
      await refreshFeedbackIndex();
      setMsg(`已撤回反馈：${c.case_id}`);
    } catch (e) { setErr(String(e.message || e)); }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="page-title">用例生成流水线</div>
          <div className="page-sub">Slicer → Generator → Merger → Validator 四步 Map-Reduce。每步可回滚、可手动编辑后续自动失效。</div>
        </div>
      </div>

      {err && <div className="err" style={{ marginBottom: 10 }}>{err}</div>}
      {msg && <div className="ok"  style={{ marginBottom: 10 }}>{msg}</div>}
      {!project && <div className="muted">请先在「项目管理」选择一个项目。</div>}

      {project && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 16, alignItems: 'start' }}>
          {/* Left: list + new */}
          <div>
            <div className="card" style={{ margin: 0, marginBottom: 12 }}>
              <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="mi" style={{ color: '#cfbcff' }}>add_circle</span>
                新建流水线
              </h3>
              <textarea
                rows={3} style={{ width: '100%', marginTop: 8 }}
                placeholder="例：针对登录模块生成测试用例"
                value={question}
                onChange={e => setQuestion(e.target.value)}
              />
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                <AiModelSelect
                  value={selectedModel}
                  onChange={setSelectedModel}
                  defaultModel={defaultModel}
                  disabled={busy}
                  title="选择用例流水线模型"
                />
                <button className="primary" disabled={busy} onClick={startNew}>
                  <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>play_arrow</span>
                  开始新流水线
                </button>
              </div>
            </div>

            <div className="card" style={{ margin: 0 }}>
              <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="mi" style={{ color: '#cfbcff' }}>list_alt</span>
                历史流水线
                <button className="icon-btn" onClick={refreshList} style={{ marginLeft: 'auto' }} title="刷新">
                  <span className="mi" style={{ fontSize: 16 }}>refresh</span>
                </button>
              </h3>
              {list.length === 0 && <div className="muted" style={{ marginTop: 8 }}>暂无流水线</div>}
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
                {list.map(p => (
                  <button
                    key={p.pipeline_id}
                    onClick={() => loadPipeline(p.pipeline_id)}
                    className={pid === p.pipeline_id ? 'active' : ''}
                    style={{
                      textAlign: 'left', padding: '8px 10px', borderRadius: 8,
                      border: pid === p.pipeline_id ? '1px solid #cfbcff' : '1px solid #2b292f',
                      background: pid === p.pipeline_id ? 'rgba(207,188,255,0.08)' : 'transparent',
                      cursor: 'pointer',
                    }}
                  >
                    <div className="mono" style={{ fontSize: 11, color: '#948e9c' }}>{p.pipeline_id}</div>
                    <div style={{ fontSize: 13, marginTop: 2 }}>{p.question || '—'}</div>
                    <div style={{ fontSize: 11, color: '#948e9c', marginTop: 2 }}>
                      {p.current_step} · {fmtTime(p.updated_at)}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Right: detail */}
          <div>
            {!selected && (
              <div className="card" style={{ margin: 0 }}>
                <div className="muted">选择左侧一条流水线，或新建一条开始。</div>
              </div>
            )}

            {selected && (
              <>
                <div className="card" style={{ margin: 0, marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <h3 style={{ margin: 0 }}>{state.pipeline_id}</h3>
                    <span className="tag info" style={{ marginLeft: 'auto' }}>{state.current_step}</span>
                  </div>
                  <div className="muted" style={{ marginTop: 6, fontSize: 13 }}>{state.question}</div>
                  <div className="mono" style={{ marginTop: 4, fontSize: 11, color: '#948e9c' }}>
                    创建 {fmtTime(state.created_at)} · 更新 {fmtTime(state.updated_at)} · 模型 {state.llm_cfg_snapshot?.model}
                  </div>
                </div>

                {[1, 2, 3, 4].map(n => {
                  const ss = state.steps?.[`step${n}`] || {};
                  const out = outputs[String(n)];
                  return (
                    <div key={n} className="card" style={{ margin: 0, marginBottom: 12 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <h3 style={{ margin: 0, fontSize: 15 }}>{STEP_LABELS[n]}</h3>
                        <StatusTag status={ss.status} />
                        {ss.user_edited && <span className="tag warn" style={{ fontSize: 11 }}>用户编辑</span>}
                        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end', maxWidth: '100%' }}>
                          <AiModelSelect
                            value={selectedModel}
                            onChange={setSelectedModel}
                            defaultModel={defaultModel}
                            disabled={busy}
                            title={`选择 ${STEP_LABELS[n]} 运行模型`}
                          />
                          <button className="ghost" disabled={busy} onClick={() => runStep(n)}>
                            <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>play_arrow</span>
                            运行
                          </button>
                          <button className="ghost" disabled={busy || ss.status === 'pending'} onClick={() => rollback(n)}>
                            <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>undo</span>
                            回滚
                          </button>
                        </div>
                      </div>
                      <div className="muted" style={{ marginTop: 4, fontSize: 11 }}>
                        {ss.llm_calls ? `LLM 调用 ${ss.llm_calls} · ` : ''}
                        {ss.tokens_in ? `in ${ss.tokens_in} · ` : ''}
                        {ss.tokens_out ? `out ${ss.tokens_out} · ` : ''}
                        {ss.duration_ms ? `${ss.duration_ms}ms` : ''}
                      </div>
                      {ss.error && <div className="err" style={{ marginTop: 6 }}>{ss.error}</div>}
                      {out && (
                        <details style={{ marginTop: 8 }}>
                          <summary className="muted" style={{ fontSize: 12, cursor: 'pointer' }}>查看产物 JSON</summary>
                          <pre style={{
                            whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 260,
                            overflow: 'auto', fontSize: 11, background: '#1a191d',
                            padding: 10, borderRadius: 6, marginTop: 6,
                          }}>{JSON.stringify(out, null, 2)}</pre>
                        </details>
                      )}
                    </div>
                  );
                })}

                <div className="card" style={{ margin: 0, marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <h3 style={{ margin: 0, fontSize: 15, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span className="mi" style={{ color: '#cfbcff' }}>insights</span>
                      覆盖率
                    </h3>
                    <button className="ghost" style={{ marginLeft: 'auto' }} disabled={covBusy} onClick={computeCoverage}>
                      <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>
                        {covBusy ? 'hourglass_top' : 'calculate'}
                      </span>
                      {covBusy ? '计算中…' : '计算/刷新覆盖率'}
                    </button>
                  </div>
                  {coverage && (
                    <div style={{ marginTop: 10, fontSize: 13 }}>
                      <div>KP 总数 <b>{coverage.total_kps}</b> · 用例总数 <b>{coverage.total_cases}</b></div>
                      {coverage.tier_counts && (
                        <div className="muted" style={{ marginTop: 4 }}>
                          explicit {coverage.tier_counts.explicit ?? 0} ·
                          same_chunk {coverage.tier_counts.same_chunk ?? 0} ·
                          semantic {coverage.tier_counts.semantic ?? 0} ·
                          uncovered {coverage.tier_counts.uncovered ?? 0}
                        </div>
                      )}
                      {typeof coverage.weighted_score === 'number' && (
                        <div style={{ marginTop: 4 }}>加权分 <b>{coverage.weighted_score.toFixed(3)}</b></div>
                      )}
                    </div>
                  )}
                  {!coverage && <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>尚未计算覆盖率</div>}
                </div>

                {cases && (
                  <div className="card" style={{ margin: 0 }}>
                    <h3 style={{ margin: 0, fontSize: 15, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span className="mi" style={{ color: '#7fd9a8' }}>task_alt</span>
                      当前用例（{cases.length}）
                    </h3>
                    <div style={{ marginTop: 8, maxHeight: 400, overflow: 'auto', fontSize: 12 }}>
                      {cases.map((c, i) => {
                        const fb = fbByCase[c.case_id];
                        return (
                          <div key={c.case_id || i} style={{
                            padding: '8px 10px', borderBottom: '1px solid #2b292f',
                          }}>
                            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                              <span className="mono" style={{ color: '#948e9c' }}>{c.case_id}</span>
                              <span className="tag" style={{ fontSize: 10 }}>{c.priority}</span>
                              <span className="tag info" style={{ fontSize: 10 }}>{c.category}</span>
                              {fbEnabled && (
                                <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
                                  <button
                                    className="icon-btn"
                                    title={fb?.kind === 'up' ? '撤回👍' : '标记为好用例'}
                                    onClick={() => fb?.kind === 'up' ? withdrawFeedback(c) : sendFeedback(c, 'up')}
                                    style={{
                                      fontSize: 14, padding: '2px 6px',
                                      background: fb?.kind === 'up' ? 'rgba(127,217,168,0.18)' : 'transparent',
                                      color: fb?.kind === 'up' ? '#7fd9a8' : '#948e9c',
                                    }}
                                  >
                                    <span className="mi" style={{ fontSize: 14 }}>thumb_up</span>
                                  </button>
                                  <button
                                    className="icon-btn"
                                    title={fb?.kind === 'down' ? '撤回👎' : '标记为不满意'}
                                    onClick={() => fb?.kind === 'down' ? withdrawFeedback(c) : sendFeedback(c, 'down')}
                                    style={{
                                      fontSize: 14, padding: '2px 6px',
                                      background: fb?.kind === 'down' ? 'rgba(255,180,171,0.18)' : 'transparent',
                                      color: fb?.kind === 'down' ? '#ffb4ab' : '#948e9c',
                                    }}
                                  >
                                    <span className="mi" style={{ fontSize: 14 }}>thumb_down</span>
                                  </button>
                                </div>
                              )}
                            </div>
                            <div style={{ marginTop: 4, fontWeight: 500 }}>{c.title}</div>
                            <div className="muted" style={{ marginTop: 2, fontSize: 11 }}>
                              FP {c.feature_point} · 期望 {c.expected_result}
                            </div>
                            {fb?.note && (
                              <div className="muted" style={{ marginTop: 2, fontSize: 11, fontStyle: 'italic' }}>
                                反馈备注：{fb.note}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
