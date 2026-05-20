const API_BASE = '/api';

// API Key 简单编码（Base64），防止明文抓包
const encodeApiKey = (key) => {
  if (!key) return key;
  try {
    return btoa(unescape(encodeURIComponent(key)));
  } catch (e) {
    return key;
  }
};

// 递归处理请求体中的 api_key 字段
const protectApiKey = (obj) => {
  if (!obj || typeof obj !== 'object') return obj;
  const copy = Array.isArray(obj) ? [] : {};
  for (const [k, v] of Object.entries(obj)) {
    if (k === 'api_key' && typeof v === 'string' && v.trim()) {
      copy[k] = encodeApiKey(v);
    } else if (typeof v === 'object' && v !== null) {
      copy[k] = protectApiKey(v);
    } else {
      copy[k] = v;
    }
  }
  return copy;
};

async function req(path, opts = {}) {
  // 对 POST/PUT 请求体中的 api_key 进行编码
  if ((opts.method === 'POST' || opts.method === 'PUT') && opts.body && opts.headers?.['Content-Type'] === 'application/json') {
    try {
      const parsed = JSON.parse(opts.body);
      opts.body = JSON.stringify(protectApiKey(parsed));
    } catch (e) {
      // ignore
    }
  }
  const res = await fetch(`${API_BASE}${path}`, opts);
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!res.ok) {
    const msg = data?.detail || data?.raw || res.statusText;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return data;
}

const q = (obj) => new URLSearchParams(obj).toString();

export const api = {
  // projects
  listProjects: () => req('/projects'),
  createProject: (name) => req('/projects', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  }),
  stats: (name) => req(`/projects/${encodeURIComponent(name)}/stats`),
  deleteProject: (name) => req('/projects', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  }),

  // folders
  listFolders: (project) => req(`/folders?${q({ project })}`),
  listFolderFiles: (project, path) => req(`/folders/files?${q({ project, path })}`),
  addFolder: (project, path) => req('/folders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, path }),
  }),
  removeFolder: (project, path) => req('/folders', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, path }),
  }),
  openFile: (project, path) => req('/folders/open', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, path }),
  }),

  // scan / build
  scan: (project) => req('/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project }),
  }),
  buildMemory: (project, llm, { force_files = null, rebuild_all = false, incremental = true } = {}) =>
    req('/memory/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, llm, force_files, rebuild_all, incremental }),
    }),

  // memory
  getMemory: (project) => req(`/memory?${q({ project })}`),
  saveMemory: (project, memory_md, regenerate_prompt = true) => req('/memory', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, memory_md, regenerate_prompt }),
  }),
  savePrompt: (project, prompt_text) => req('/memory/prompt', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, prompt_text }),
  }),

  // query
  query: (project, question, mode, llm, top_k = null, history = null, mentions = null) => req('/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, question, mode, top_k, llm, history, mentions }),
  }),

  // augment memory with user-supplied info
  augmentMemory: (project, info, llm, note = '') => req('/memory/augment', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, info, note, llm }),
  }),

  // memory versions
  listVersions: (project) => req(`/memory/versions?${q({ project })}`),
  getVersion: (project, versionId) =>
    req(`/memory/versions/${encodeURIComponent(versionId)}?${q({ project })}`),
  restoreVersion: (project, versionId) =>
    req(`/memory/versions/${encodeURIComponent(versionId)}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project }),
    }),

  // build history
  listBuilds: (project) => req(`/memory/builds?${q({ project })}`),
  getBuild: (project, buildId) =>
    req(`/memory/builds/${encodeURIComponent(buildId)}?${q({ project })}`),
  restoreFromBuild: (project, buildId) =>
    req(`/memory/builds/${encodeURIComponent(buildId)}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project }),
    }),

  // ---- legacy assets (历史用例 / 历史 XMind / 反哺候选) ----
  legacyListCases: (project) => req(`/legacy/cases?${q({ project })}`),
  legacyPeekHeaders: (project, file) => {
    const fd = new FormData();
    fd.append('project', project);
    fd.append('file', file);
    return req('/legacy/cases/peek-headers', { method: 'POST', body: fd });
  },
  legacyUploadCase: (project, file, confirmed_mapping = null) => {
    const fd = new FormData();
    fd.append('project', project);
    fd.append('file', file);
    if (confirmed_mapping) fd.append('confirmed_mapping', JSON.stringify(confirmed_mapping));
    return req('/legacy/cases/upload', { method: 'POST', body: fd });
  },
  legacyGetCaseFile: (project, fileId) =>
    req(`/legacy/cases/${encodeURIComponent(fileId)}?${q({ project })}`),
  legacyDeleteCase: (project, fileId) =>
    req(`/legacy/cases/${encodeURIComponent(fileId)}?${q({ project })}`, { method: 'DELETE' }),

  legacyListXMind: (project) => req(`/legacy/xmind?${q({ project })}`),
  legacyUploadXMind: (project, file) => {
    const fd = new FormData();
    fd.append('project', project);
    fd.append('file', file);
    return req('/legacy/xmind/upload', { method: 'POST', body: fd });
  },
  legacyGetXMind: (project, fileId) =>
    req(`/legacy/xmind/${encodeURIComponent(fileId)}?${q({ project })}`),
  legacyDeleteXMind: (project, fileId) =>
    req(`/legacy/xmind/${encodeURIComponent(fileId)}?${q({ project })}`, { method: 'DELETE' }),

  legacyGetColumnMapping: (project) => req(`/legacy/column-mapping?${q({ project })}`),
  legacyConfirmColumnMapping: (project, fingerprint, mapping) =>
    req('/legacy/column-mapping/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, fingerprint, mapping }),
    }),

  legacyGetStyle: (project) => req(`/legacy/style?${q({ project })}`),

  legacyListInferred: (project, status = null) => {
    const params = { project };
    if (status) params.status = status;
    return req(`/legacy/inferred?${q(params)}`);
  },
  legacyReviewInferred: (project, inferred_id, decision, reviewer = '') =>
    req('/legacy/inferred/review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, inferred_id, decision, reviewer }),
    }),
  legacyBatchReviewInferred: (project, inferred_ids, decision, reviewer = '') =>
    req('/legacy/inferred/batch-review', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, inferred_ids, decision, reviewer }),
    }),

  legacyAnalyze: (project, llm, { skip_extract = false } = {}) =>
    req('/legacy/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, llm, skip_extract }),
    }),

  // 分析进度控制
  legacyAnalysisProgress: (project) =>
    req(`/legacy/analyze/progress?${q({ project })}`),
  
  legacyAnalysisPause: (project) =>
    req(`/legacy/analyze/pause?${q({ project })}`, {
      method: 'POST',
    }),
  
  legacyAnalysisResume: (project) =>
    req(`/legacy/analyze/resume?${q({ project })}`, {
      method: 'POST',
    }),
  
  legacyAnalysisCancel: (project) =>
    req(`/legacy/analyze/cancel?${q({ project })}`, {
      method: 'POST',
    }),

  // memory build progress control
  getMemoryBuildProgress: (project) =>
    req(`/memory/build/progress?${q({ project })}`),
  
  pauseMemoryBuild: (project) =>
    req(`/memory/build/pause?${q({ project })}`, {
      method: 'POST',
    }),
  
  resumeMemoryBuild: (project) =>
    req(`/memory/build/resume?${q({ project })}`, {
      method: 'POST',
    }),
  
  cancelMemoryBuild: (project) =>
    req(`/memory/build/cancel?${q({ project })}`, {
      method: 'POST',
    }),

  // diagnostics
  checkEnv: (api_key) => req('/debug/env-check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key }),
  }),

  // ---- feature flags -----------------------------------------------------
  getFeatures: () => req('/settings/features'),
  updateFeatures: (partial) => req('/settings/features', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(partial),
  }),

  // ---- case-gen pipeline -------------------------------------------------
  cgStart: (project, question, llm, { mentions = null, filters = null } = {}) =>
    req('/case-gen/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project, question, llm, mentions, filters }),
    }),
  cgList: (project) => req(`/case-gen/list?${q({ project })}`),
  cgGet: (project, pipelineId) =>
    req(`/case-gen/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}`),
  cgRunStep: (project, pipelineId, n, llm) =>
    req(`/case-gen/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}/step/${n}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm }),
    }),
  cgUserEdit: (project, pipelineId, n, payload) =>
    req(`/case-gen/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}/step/${n}/output`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload }),
    }),
  cgRollback: (project, pipelineId, step_n) =>
    req(`/case-gen/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}/rollback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step_n }),
    }),

  // ---- conflict detection ------------------------------------------------
  cfDetect: (project, llm, { sim_low = 0.75, sim_high = 0.99, modules = null } = {}) =>
    req(`/conflict/${encodeURIComponent(project)}/detect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ llm, sim_low, sim_high, modules }),
    }),
  cfList: (project) => req(`/conflict/${encodeURIComponent(project)}`),
  cfResolve: (project, conflictId, resolution, note = '') =>
    req(`/conflict/${encodeURIComponent(project)}/${encodeURIComponent(conflictId)}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resolution, note }),
    }),
  cfDelete: (project, conflictId) =>
    req(`/conflict/${encodeURIComponent(project)}/${encodeURIComponent(conflictId)}`, {
      method: 'DELETE',
    }),
  cfClear: (project) =>
    req(`/conflict/${encodeURIComponent(project)}`, { method: 'DELETE' }),

  // ---- feedback loop -----------------------------------------------------
  fbSubmit: (project, body) =>
    req(`/feedback/${encodeURIComponent(project)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  fbList: (project, { kind = null, target_id = null } = {}) => {
    const params = {};
    if (kind) params.kind = kind;
    if (target_id) params.target_id = target_id;
    const qs = Object.keys(params).length ? `?${q(params)}` : '';
    return req(`/feedback/${encodeURIComponent(project)}${qs}`);
  },
  fbSummary: (project) =>
    req(`/feedback/${encodeURIComponent(project)}/summary`),
  fbExamples: (project, { module = null, limit = 3 } = {}) => {
    const params = { limit };
    if (module) params.module = module;
    return req(`/feedback/${encodeURIComponent(project)}/examples?${q(params)}`);
  },
  fbDelete: (project, feedbackId) =>
    req(`/feedback/${encodeURIComponent(project)}/${encodeURIComponent(feedbackId)}`, {
      method: 'DELETE',
    }),
  fbClear: (project) =>
    req(`/feedback/${encodeURIComponent(project)}`, { method: 'DELETE' }),

  // ---- coverage ----------------------------------------------------------
  covCompute: (project, pipelineId, { sim_threshold = 0.75, enable_semantic = true } = {}) =>
    req(`/coverage/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}/compute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sim_threshold, enable_semantic }),
    }),
  covGet: (project, pipelineId) =>
    req(`/coverage/${encodeURIComponent(project)}/${encodeURIComponent(pipelineId)}`),
  covSummary: (project) => req(`/coverage/${encodeURIComponent(project)}/summary`),

  // outputs
  listOutputs: (project, kind = null) => {
    const params = { project };
    if (kind) params.kind = kind;
    return req(`/outputs?${q(params)}`);
  },
  getOutputContent: (project, kind, filename) =>
    req(`/outputs/content?${q({ project, kind, filename })}`),
  renameOutput: (project, kind, old_name, new_name) => req('/outputs/rename', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, kind, old_name, new_name }),
  }),
  deleteOutput: (project, kind, filename) => req('/outputs', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project, kind, filename }),
  }),
};
