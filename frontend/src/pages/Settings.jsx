import React, { useState, useEffect } from 'react';
import { api } from '../api.js';
import { useLLMStore, useStreamOutput } from '../store.js';

const OPENROUTER_MODELS = [
  'openai/gpt-5.5-20260423',
  'anthropic/claude-4.5-haiku-20251001',
  'anthropic/claude-4.6-sonnet-20260217',
  'anthropic/claude-4.7-opus-20260416',
  'bytedance-seed/seed-2.0-lite-20260309',
  'bytedance-seed/seed-2.0-mini-20260224',
  'deepseek/deepseek-v3.2-20251201',
  'deepseek/deepseek-v4-flash-20260423',
  'deepseek/deepseek-v4-pro-20260423',
  'google/gemini-3.1-flash-image-preview-20260226',
  'google/gemini-3.1-flash-lite-preview-20260303',
  'google/gemini-3.1-pro-preview-20260219',
  'minimax/minimax-m2.7-20260318',
  'moonshotai/kimi-k2.5-0127',
  'moonshotai/kimi-k2.6-20260420',
  'openai/gpt-5.4-20260305',
  'openai/gpt-5.4-mini-20260317',
  'openai/gpt-5.4-nano-20260317',
  'qwen/qwen3.5-flash-20260224',
  'qwen/qwen3.6-plus-04-02',
  'x-ai/grok-4.20-20260309',
  'xiaomi/mimo-v2.5-20260422',
  'xiaomi/mimo-v2.5-pro-20260422',
  'z-ai/glm-5.1-20260406',
];

const PROVIDERS = {
  openrouter: {
    label: 'OpenRouter',
    icon: 'hub',
    models: OPENROUTER_MODELS,
    sub: '自动路由全球顶尖大模型节点，优化成本。',
  },
};

function Toggle({ checked, onChange }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      style={{
        width: 44, height: 24,
        borderRadius: 12,
        border: 'none',
        background: checked ? 'linear-gradient(135deg, #cfbcff, #9a7cff)' : '#36343a',
        position: 'relative', cursor: 'pointer',
        transition: 'all 160ms ease',
        boxShadow: checked ? '0 0 12px rgba(207,188,255,0.3)' : 'none',
      }}
    >
      <span style={{
        position: 'absolute', top: 3, left: checked ? 23 : 3,
        width: 18, height: 18, borderRadius: '50%',
        background: '#fff', transition: 'left 160ms ease',
      }} />
    </button>
  );
}

// 识别环境变量引用：裸 NAME / $NAME / ${NAME} / ${env:NAME}
const ENV_NAME_RE = /^(?:\$\{\s*(?:env[:.])?\s*([A-Za-z_][A-Za-z0-9_]{1,63})\s*\}|\$([A-Za-z_][A-Za-z0-9_]{1,63})|([A-Z][A-Z0-9_]{1,63}))$/;

function detectEnvVar(s) {
  const v = (s || '').trim();
  if (!v) return null;
  const m = ENV_NAME_RE.exec(v);
  if (!m) return null;
  return m[1] || m[2] || m[3] || null;
}

const FEISHU_SUBFEATURES = [
  { key: 'f1_import', label: 'F1 飞书云文档导入历史用例', desc: '从多维表格/Sheet 拉取记录，复用历史用例 ingest 流水线。' },
  { key: 'f2_sync', label: 'F2 文档变更自动同步', desc: '订阅源文档变更，Webhook 触发增量重解析。需 drive:subscribe 权限。' },
  { key: 'f3_done_notify', label: 'F3 解析完成 Bot 推送', desc: '用例解析/分析完成后向负责人推送摘要卡片。' },
  { key: 'f4_error_alert', label: 'F4 异常 Warning Bot 告警', desc: '出现 error 级 warning 时自动 @负责人 告警。' },
  { key: 'f6_review_card', label: 'F6 反哺候选 Bot 审核', desc: '新 pending 知识点推卡片，支持飞书内直接「通过/拒绝」。' },
  { key: 'f8_export_sheet', label: 'F8 用例导出飞书电子表格', desc: '一键生成飞书 Sheet，返回分享链接。固定 9 列结构。' },
  { key: 'f9_im_bot', label: 'F9 AI 对话接入飞书机器人', desc: '@机器人发起多模式对话（问答/用例生成/反哺审核）。需 im:message 权限。' },
];

function FeishuIntegrationCard({ globalEnabled }) {
  const [projects, setProjects] = useState([]);
  const [project, setProject] = useState('');
  const [cfg, setCfg] = useState(null);
  const [appSecretDraft, setAppSecretDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [testResult, setTestResult] = useState(null);

  useEffect(() => {
    if (!globalEnabled) return;
    api.listProjects().then(list => {
      const names = (list || []).map(p => p.name || p);
      setProjects(names);
      if (names.length && !project) setProject(names[0]);
    }).catch(e => setErr(String(e.message || e)));
    // eslint-disable-next-line
  }, [globalEnabled]);

  useEffect(() => {
    if (!project) { setCfg(null); return; }
    setErr('');
    setTestResult(null);
    api.feishuGetConfig(project).then(setCfg).catch(e => setErr(String(e.message || e)));
  }, [project]);

  async function save(patch) {
    if (!project) return;
    setSaving(true);
    setErr('');
    try {
      const body = { ...patch };
      if (appSecretDraft) {
        body.app_secret = appSecretDraft;
        setAppSecretDraft('');
      }
      const next = await api.feishuSaveConfig(project, body);
      setCfg(next);
    } catch (e) {
      setErr(String(e.message || e));
    }
    setSaving(false);
  }

  async function runTest() {
    if (!project) return;
    setTestResult(null);
    try {
      const r = await api.feishuTest(project);
      setTestResult(r);
    } catch (e) {
      setTestResult({ token_ok: false, error: String(e.message || e) });
    }
  }

  if (!globalEnabled) {
    return (
      <div className="card" style={{ margin: 0, marginBottom: 16, opacity: 0.7 }}>
        <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="mi" style={{ color: '#7fb4ff' }}>integration_instructions</span>
          飞书集成
        </h3>
        <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          请先在上方「实验性功能」中打开「飞书集成（总开关）」。
        </div>
      </div>
    );
  }

  return (
    <div className="card" style={{ margin: 0, marginBottom: 16 }}>
      <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className="mi" style={{ color: '#7fb4ff' }}>integration_instructions</span>
        飞书集成
      </h3>
      <div className="muted" style={{ fontSize: 12, lineHeight: 1.6, marginTop: 4, marginBottom: 12 }}>
        每个项目独立配置一组应用凭据；app_secret 落盘前用 Fernet 加密（若 <code className="mono">CASEMIND_MASTER_KEY</code> 未设置则降级明文存储 + 审计标记）。
      </div>

      <div style={{ marginBottom: 12 }}>
        <label className="muted mono" style={{ display: 'block', fontSize: 11, marginBottom: 4 }}>项目</label>
        <select style={{ width: '100%' }} value={project} onChange={e => setProject(e.target.value)}>
          {projects.length === 0 && <option value="">（暂无项目）</option>}
          {projects.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
      </div>

      {err && <div className="err" style={{ marginBottom: 8 }}>{err}</div>}

      {cfg && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '10px 0', borderBottom: '1px solid #2b292f' }}>
            <div>
              <div style={{ fontWeight: 500 }}>项目级启用飞书集成</div>
              <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>关闭后该项目下所有飞书路由返回 403。</div>
            </div>
            <Toggle checked={!!cfg.enabled} onChange={(v) => save({ enabled: v })} />
          </div>

          <div style={{ marginTop: 12 }}>
            <label className="muted mono" style={{ fontSize: 11 }}>App ID</label>
            <input style={{ width: '100%' }} value={cfg.app_id || ''}
              onChange={e => setCfg({ ...cfg, app_id: e.target.value })}
              onBlur={() => save({ app_id: cfg.app_id || '' })}
              placeholder="cli_xxxxxxxxxxxx" />
          </div>

          <div style={{ marginTop: 12 }}>
            <label className="muted mono" style={{ fontSize: 11 }}>
              App Secret
              {cfg.app_secret_configured && <span className="tag ok" style={{ marginLeft: 8 }}>已配置</span>}
              {cfg.security_warning && <span className="tag warn" style={{ marginLeft: 8 }}>{cfg.security_warning}</span>}
            </label>
            <input style={{ width: '100%' }} type="password" value={appSecretDraft}
              onChange={e => setAppSecretDraft(e.target.value)}
              placeholder={cfg.app_secret_configured ? '（已存储，留空表示不修改）' : '填入飞书 App Secret'} />
            {appSecretDraft && (
              <button className="ghost" style={{ marginTop: 6, fontSize: 12 }}
                onClick={() => save({})} disabled={saving}>提交并加密落盘</button>
            )}
          </div>

          <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div>
              <label className="muted mono" style={{ fontSize: 11 }}>Verify Token</label>
              <input style={{ width: '100%' }} value={cfg.verify_token || ''}
                onChange={e => setCfg({ ...cfg, verify_token: e.target.value })}
                onBlur={() => save({ verify_token: cfg.verify_token || '' })} />
            </div>
            <div>
              <label className="muted mono" style={{ fontSize: 11 }}>Encrypt Key</label>
              <input style={{ width: '100%' }} value={cfg.encrypt_key || ''}
                onChange={e => setCfg({ ...cfg, encrypt_key: e.target.value })}
                onBlur={() => save({ encrypt_key: cfg.encrypt_key || '' })} />
            </div>
          </div>

          <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <div>
              <label className="muted mono" style={{ fontSize: 11 }}>导出文件夹 Token</label>
              <input style={{ width: '100%' }} value={cfg.folder_token || ''}
                onChange={e => setCfg({ ...cfg, folder_token: e.target.value })}
                onBlur={() => save({ folder_token: cfg.folder_token || '' })}
                placeholder="飞书云空间 folder_token，用于 F8 落盘位置" />
            </div>
            <div>
              <label className="muted mono" style={{ fontSize: 11 }}>默认群 chat_id</label>
              <input style={{ width: '100%' }} value={cfg.default_chat_id || ''}
                onChange={e => setCfg({ ...cfg, default_chat_id: e.target.value })}
                onBlur={() => save({ default_chat_id: cfg.default_chat_id || '' })} />
            </div>
          </div>

          <div style={{ marginTop: 16 }}>
            <div className="muted mono" style={{ fontSize: 11, marginBottom: 6 }}>负责人列表（用于 @ 提醒）</div>
            {(cfg.owners || []).map((o, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                <input style={{ flex: 1 }} value={o.name} placeholder="姓名"
                  onChange={e => {
                    const next = [...cfg.owners]; next[i] = { ...o, name: e.target.value };
                    setCfg({ ...cfg, owners: next });
                  }}
                  onBlur={() => save({ owners: cfg.owners })} />
                <input style={{ flex: 2 }} value={o.open_id} placeholder="ou_xxxxxx"
                  onChange={e => {
                    const next = [...cfg.owners]; next[i] = { ...o, open_id: e.target.value };
                    setCfg({ ...cfg, owners: next });
                  }}
                  onBlur={() => save({ owners: cfg.owners })} />
                <button className="ghost" onClick={() => {
                  const next = (cfg.owners || []).filter((_, j) => j !== i);
                  setCfg({ ...cfg, owners: next });
                  save({ owners: next });
                }}>删</button>
              </div>
            ))}
            <button className="ghost" style={{ fontSize: 12 }} onClick={() => {
              const next = [...(cfg.owners || []), { name: '', open_id: '' }];
              setCfg({ ...cfg, owners: next });
            }}>+ 添加负责人</button>
          </div>

          <div style={{ marginTop: 16 }}>
            <div className="muted mono" style={{ fontSize: 11, marginBottom: 6 }}>子功能开关</div>
            {FEISHU_SUBFEATURES.map(sf => (
              <div key={sf.key} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '8px 0', borderBottom: '1px solid #2b292f',
                opacity: cfg.enabled ? 1 : 0.5,
              }}>
                <div style={{ paddingRight: 12, flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 500 }}>{sf.label}</div>
                  <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{sf.desc}</div>
                </div>
                <Toggle
                  checked={!!(cfg.subfeatures && cfg.subfeatures[sf.key])}
                  onChange={(v) => {
                    const nextSub = { ...(cfg.subfeatures || {}), [sf.key]: v };
                    setCfg({ ...cfg, subfeatures: nextSub });
                    save({ subfeatures: nextSub });
                  }}
                />
              </div>
            ))}
          </div>

          <div style={{ marginTop: 16 }}>
            <button className="ghost" onClick={runTest}>
              <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>cable</span>
              连接测试
            </button>
            {testResult && (
              <div style={{ marginTop: 10, padding: '10px 12px', borderRadius: 8, fontSize: 12,
                background: testResult.token_ok ? 'rgba(127,217,168,0.12)' : 'rgba(255,180,171,0.12)',
                border: `1px solid ${testResult.token_ok ? 'rgba(127,217,168,0.4)' : 'rgba(255,180,171,0.4)'}` }}>
                {testResult.using_mock && (
                  <div className="tag warn" style={{ marginBottom: 6 }}>Mock 模式（App ID 未填）</div>
                )}
                {testResult.error && <div className="err">{testResult.error}</div>}
                {testResult.scopes && (
                  <div className="mono" style={{ lineHeight: 1.8 }}>
                    {Object.entries(testResult.scopes).map(([k, v]) => (
                      <div key={k}>
                        <span style={{ color: v === 'ok' || v === 'mock' ? '#7fd9a8' : '#ffb4ab' }}>{v}</span>
                        {' · '}{k}
                      </div>
                    ))}
                  </div>
                )}
                {testResult.security_warning && (
                  <div className="tag warn" style={{ marginTop: 8 }}>{testResult.security_warning}</div>
                )}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export default function Settings() {
  const [store, { setActive, setProfile }] = useLLMStore();
  const active = store.active;
  const activeProfile = store.profiles[active] || { base_url: '', api_key: '', model: '' };

  // 编辑态：每次切 provider 重置为该 profile
  const [draft, setDraft] = useState(activeProfile);
  useEffect(() => { setDraft(activeProfile); /* eslint-disable-next-line */ }, [active]);

  const [msg, setMsg] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [ctxCompress, setCtxCompress] = useState(true);
  const [streamOutput, setStreamOutput] = useStreamOutput();
  const [envDiag, setEnvDiag] = useState(null);
  const [checking, setChecking] = useState(false);

  // ---- 实验性功能 (features flag) ----
  const [features, setFeatures] = useState(null);
  const [featuresErr, setFeaturesErr] = useState('');
  const [featuresSaving, setFeaturesSaving] = useState(false);
  useEffect(() => {
    api.getFeatures().then(setFeatures).catch(e => setFeaturesErr(String(e.message || e)));
  }, []);

  async function toggleFeature(key, val) {
    if (!features) return;
    setFeaturesSaving(true);
    try {
      const next = await api.updateFeatures({ [key]: val });
      setFeatures(next);
      // 重要：case-gen 开关翻转时需让 Sidebar 重绘
      window.dispatchEvent(new Event('casemind:features'));
    } catch (e) {
      setFeaturesErr(String(e.message || e));
    }
    setFeaturesSaving(false);
  }

  const envName = detectEnvVar(draft.api_key);

  async function runEnvCheck() {
    setChecking(true);
    setEnvDiag(null);
    try {
      const r = await api.checkEnv(draft.api_key || '');
      setEnvDiag(r);
    } catch (e) {
      setEnvDiag({ verdict: 'error', hint: String(e.message || e) });
    }
    setChecking(false);
  }

  function switchProvider(key) {
    // 切换前，先把当前草稿落盘到当前 provider 的 profile，避免"切走就丢"
    if (JSON.stringify(draft) !== JSON.stringify(activeProfile)) {
      setProfile(active, draft);
    }
    setActive(key);
    setEnvDiag(null);
  }

  function save() {
    setProfile(active, draft);
    setMsg(`已保存 ${PROVIDERS[active]?.label || active} 的配置到本地浏览器 (localStorage)`);
    setTimeout(() => setMsg(''), 2500);
  }

  const models = PROVIDERS[active]?.models || [];

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="page-title">设置与安全</div>
          <div className="page-sub">配置 OpenRouter 接入参数与本地数据策略。key / base_url / model 保存在当前浏览器本地。</div>
        </div>
        <button className="ghost" onClick={save}>
          <span className="mi" style={{ fontSize: 16, verticalAlign: -3, marginRight: 4 }}>save</span>
          保存所有
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, alignItems: 'start' }}>
        {/* Left: Provider + form */}
        <div>
          <div className="card" style={{ margin: 0, marginBottom: 16 }}>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="mi" style={{ color: '#cfbcff' }}>bolt</span>
              AI 提供商
            </h3>
            <div className="provider-grid" style={{ marginTop: 12 }}>
              {Object.entries(PROVIDERS).map(([k, v]) => {
                const prof = store.profiles[k] || {};
                const hasKey = !!(prof.api_key && prof.api_key.trim());
                return (
                  <div
                    key={k}
                    className={`provider-card ${active === k ? 'active' : ''}`}
                    onClick={() => switchProvider(k)}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                      <span className="mi" style={{ color: active === k ? '#cfbcff' : '#948e9c' }}>{v.icon}</span>
                      <div className="p-name">{v.label}</div>
                      {active === k && <span className="tag info" style={{ marginLeft: 'auto' }}>已启用</span>}
                      {active !== k && hasKey && (
                        <span className="tag ok" style={{ marginLeft: 'auto', fontSize: 10 }}>已配置</span>
                      )}
                    </div>
                    <div className="p-sub">{v.sub}</div>
                  </div>
                );
              })}
            </div>

            <div style={{ marginTop: 20 }}>
              <label className="muted mono" style={{ display: 'block', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', marginBottom: 6 }}>
                接口地址 (Base URL)
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type="text" style={{ width: '100%', paddingLeft: 36 }}
                  value={draft.base_url || ''}
                  onChange={e => setDraft({ ...draft, base_url: e.target.value })}
                />
                <span className="mi" style={{ position: 'absolute', left: 12, top: 10, color: '#948e9c', fontSize: 16 }}>link</span>
              </div>
            </div>

            <div style={{ marginTop: 16 }}>
              <label className="muted mono" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', marginBottom: 6 }}>
                <span>密钥 (API Key) · 仅对 {PROVIDERS[active]?.label} 生效</span>
                <span style={{ color: '#7fd9a8' }}>
                  <span className="mi" style={{ fontSize: 12, verticalAlign: -2 }}>lock</span> 仅本地保存
                </span>
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type={showKey || !!envName ? 'text' : 'password'}
                  style={{ width: '100%', paddingLeft: 36, paddingRight: 40, fontFamily: envName ? '"Space Grotesk", monospace' : undefined }}
                  placeholder="sk-... 或环境变量引用如 ${env:OPENROUTER_API_KEY}"
                  value={draft.api_key || ''}
                  onChange={e => setDraft({ ...draft, api_key: e.target.value })}
                />
                <span className="mi" style={{ position: 'absolute', left: 12, top: 10, color: envName ? '#7fd9a8' : '#948e9c', fontSize: 16 }}>
                  {envName ? 'terminal' : 'key'}
                </span>
                <button
                  className="icon-btn"
                  style={{ position: 'absolute', right: 6, top: 6 }}
                  onClick={() => setShowKey(v => !v)}
                  title={showKey ? '隐藏' : '显示'}
                >
                  <span className="mi" style={{ fontSize: 16 }}>{showKey ? 'visibility_off' : 'visibility'}</span>
                </button>
              </div>
              <div className="muted" style={{ marginTop: 6, fontSize: 12, lineHeight: 1.5 }}>
                {envName
                  ? <>
                      <span className="tag ok" style={{ marginRight: 6 }}>ENV</span>
                      检测到环境变量名 <code className="mono">{envName}</code>，后端将运行时从系统环境读取对应密钥。若未设置，<b>裸大写名</b>会被当作字面 key；<b>${'{env:NAME}'} / $NAME</b> 则会显式报错。
                    </>
                  : <>支持直接粘贴 key，或填写系统环境变量引用（例如 <code className="mono">ANTHROPIC_API_KEY</code>、<code className="mono">$ANTHROPIC_API_KEY</code>、<code className="mono">{'${env:ANTHROPIC_API_KEY}'}</code>）。</>
                }
              </div>
              <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center' }}>
                <button className="ghost" onClick={runEnvCheck} disabled={checking} style={{ padding: '4px 12px', fontSize: 12 }}>
                  <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>
                    {checking ? 'hourglass_top' : 'troubleshoot'}
                  </span>
                  {checking ? '检查中…' : '检查后端能否读到该密钥'}
                </button>
                <span className="muted" style={{ fontSize: 11 }}>
                  不会把密钥回传，只返回"存在/长度"等诊断信息
                </span>
              </div>
              {envDiag && (
                <div style={{
                  marginTop: 10, padding: '10px 12px', borderRadius: 8, fontSize: 12,
                  background: envDiag.verdict === 'ok' ? 'rgba(127,217,168,0.12)'
                    : envDiag.verdict === 'literal' ? 'rgba(207,188,255,0.12)'
                    : 'rgba(255,180,171,0.12)',
                  border: `1px solid ${envDiag.verdict === 'ok' ? 'rgba(127,217,168,0.4)'
                    : envDiag.verdict === 'literal' ? 'rgba(207,188,255,0.3)'
                    : 'rgba(255,180,171,0.4)'}`,
                  color: '#e6e0e9',
                }}>
                  <div style={{ fontWeight: 600, marginBottom: 6 }}>
                    <span className="mi" style={{ fontSize: 14, verticalAlign: -2, marginRight: 4 }}>
                      {envDiag.verdict === 'ok' ? 'check_circle'
                        : envDiag.verdict === 'literal' ? 'info'
                        : 'error'}
                    </span>
                    {envDiag.verdict === 'ok' ? '后端已读取到密钥'
                      : envDiag.verdict === 'literal' ? '字面密钥模式'
                      : envDiag.verdict === 'empty' ? '未填写'
                      : envDiag.verdict === 'env_missing' ? '环境变量在后端进程中不可见'
                      : '诊断异常'}
                  </div>
                  <pre style={{
                    whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                    margin: 0, fontFamily: 'inherit', color: '#cbc4d2', lineHeight: 1.6,
                  }}>{envDiag.hint || ''}</pre>
                  {envDiag.env_name && (
                    <div className="mono" style={{ marginTop: 6, fontSize: 11, color: '#b5afbd' }}>
                      变量名 <code>{envDiag.env_name}</code> · 后端 os.environ 中存在：
                      <b style={{ color: envDiag.present_in_process_env ? '#7fd9a8' : '#ffb4ab' }}>
                        {envDiag.present_in_process_env ? '是' : '否'}
                      </b>
                      {envDiag.value_length > 0 && ` · 长度 ${envDiag.value_length}`}
                      {envDiag.case_insensitive_hits?.length > 0 && (
                        <div style={{ marginTop: 4 }}>
                          <span className="tag warn" style={{ marginRight: 6 }}>大小写不同</span>
                          {envDiag.case_insensitive_hits.join(', ')}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div style={{ marginTop: 16 }}>
              <label className="muted mono" style={{ display: 'block', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', marginBottom: 6 }}>
                默认推理模型
              </label>
              <select
                style={{ width: '100%' }}
                value={draft.model || ''}
                onChange={e => setDraft({ ...draft, model: e.target.value })}
              >
                {models.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
          </div>

          <div className="card" style={{ margin: 0, marginBottom: 16 }}>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="mi" style={{ color: '#cfbcff' }}>science</span>
              实验性功能 (Feature Flags)
            </h3>
            <div className="muted" style={{ marginTop: 6, marginBottom: 12, fontSize: 12, lineHeight: 1.6 }}>
              这些能力属于 Step 3+ 架构升级，默认关闭；打开后若后端出错，旧流程不受影响。全局配置（所有项目共享），保存到 <code className="mono">memory/_global/features.json</code>。
            </div>
            {featuresErr && <div className="err" style={{ marginBottom: 8 }}>{featuresErr}</div>}
            {!features && !featuresErr && <div className="muted">加载中…</div>}
            {features && [
              { key: 'enable_knowledge_extraction', label: '结构化知识抽取',
                desc: 'MemoryAgent 末尾串联 KnowledgeExtractor，把 chunk 升级为 KnowledgePoint。' },
              { key: 'enable_hybrid_retrieval', label: '混合检索 (BM25 + 向量 + RRF)',
                desc: '关闭 = 仅向量；打开 = jieba 分词 BM25 + 向量 + RRF 融合。' },
              { key: 'enable_case_gen_pipeline', label: '用例生成流水线 (4 步 Map-Reduce)',
                desc: 'Slicer → Generator → Merger → Validator；打开后侧栏出现「用例流水线」。' },
              { key: 'enable_coverage_report', label: '覆盖率报告',
                desc: '三层命中（explicit / same_chunk / semantic）+ 加权分 + 模块聚合。' },
              { key: 'enable_conflict_detection', label: '跨文档冲突检测',
                desc: '扫描全部 KP，按模块分桶用向量相似度+LLM 裁判识别冲突对；打开后侧栏出现「冲突检测」。' },
              { key: 'enable_feedback_loop', label: '反馈闭环（👍/👎）',
                desc: '在「用例流水线」的用例卡片上启用反馈按钮；up-voted 用例会作为同模块 few-shot 注入 Step2 生成器。' },
              { key: 'enable_reranker', label: 'Rerank 精排（bge-reranker-base）',
                desc: '在混合检索 RRF 结果之上再跑一次 cross-encoder 重排；开启需要混合检索也开，模型首次使用时会下载权重（~300MB）。' },
              { key: 'enable_legacy_style_reference', label: '历史用例风格参考',
                desc: '把同模块/子项的历史用例作为 few-shot 注入用例生成器；同时把团队风格画像（步骤数/动词/标题格式）作为约束加到 system prompt。需先在「文件夹」上传历史 Excel/XMind。' },
              { key: 'enable_legacy_inference', label: '历史反哺候选审核',
                desc: '运行五阶段分析后，从历史用例反推得到的 InferredKnowledgePoint 进入 Memory 的「反哺审核」队列，人工 accept 后才可合入 KP 库。' },
              { key: 'enable_legacy_inference_auto_accept', label: '反哺候选自动接受（高风险）',
                desc: '高 confidence 的反哺候选直接合入 KP 库，跳过人工审核。仅当历史质量高度可信时启用。' },
              { key: 'enable_feishu_integration', label: '飞书集成（总开关）',
                desc: '打开后，每个项目可在下方「飞书集成」面板单独配置应用凭据、负责人与子功能（导入/导出/通知/IM）。凭据未就绪期间业务走 Mock 客户端，可端到端联调但不会真发请求。' },
            ].map(f => (
              <div key={f.key} style={{
                display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                padding: '10px 0', borderBottom: '1px solid #2b292f',
                opacity: f.disabled ? 0.45 : 1,
              }}>
                <div style={{ paddingRight: 12, flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 500, fontSize: 13 }}>{f.label}</div>
                  <div className="muted" style={{ marginTop: 2, fontSize: 12 }}>{f.desc}</div>
                </div>
                <Toggle
                  checked={!!features[f.key]}
                  onChange={(v) => !f.disabled && !featuresSaving && toggleFeature(f.key, v)}
                />
              </div>
            ))}
          </div>

          <FeishuIntegrationCard
            globalEnabled={!!(features && features.enable_feishu_integration)}
          />

          <div className="card" style={{ margin: 0 }}>
            <h3 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="mi" style={{ color: '#e7c365' }}>tune</span>
              运行参数
            </h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 0', borderBottom: '1px solid #2b292f' }}>
              <div>
                <div style={{ fontWeight: 500 }}>启用上下文压缩 (Context Compression)</div>
                <div className="muted" style={{ marginTop: 2 }}>在发送至大模型前自动压缩，节省 token 消耗。</div>
              </div>
              <Toggle checked={ctxCompress} onChange={setCtxCompress} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 0' }}>
              <div>
                <div style={{ fontWeight: 500 }}>流式输出响应 (Stream Output)</div>
                <div className="muted" style={{ marginTop: 2 }}>以打字机流式返回正文（部分接口支持）。</div>
              </div>
              <Toggle checked={streamOutput} onChange={setStreamOutput} />
            </div>
          </div>
        </div>

        {/* Right: privacy / local data */}
        <div>
          <div className="card" style={{ margin: 0 }}>
            <div style={{ textAlign: 'center', marginBottom: 12 }}>
              <div style={{
                width: 48, height: 48, borderRadius: '50%',
                background: 'rgba(207,188,255,0.12)', margin: '0 auto',
                display: 'grid', placeItems: 'center',
                boxShadow: '0 0 24px rgba(207,188,255,0.15)',
              }}>
                <span className="mi" style={{ color: '#cfbcff', fontSize: 24 }}>shield_lock</span>
              </div>
              <h3 style={{ marginTop: 12 }}>本地数据治理声明</h3>
            </div>
            <p style={{ fontSize: 13, lineHeight: 1.8, color: '#cbc4d2', margin: 0 }}>
              CaseMind 采用本地加密存储与本地优先策略：
              <br /><br />
              您上传的文档（PDF / DOCX 等）仅在您本地设备上解析、向量化，<b>不会写入后端磁盘</b>。
              如需搜索则只会上传至远端以做推理、检索，但请注意不会通过记录您的机密数据。
            </p>
          </div>
        </div>
      </div>

      {msg && <p className="ok" style={{ marginTop: 12 }}>{msg}</p>}
    </div>
  );
}
